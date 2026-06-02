import contextlib
import os
import threading
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Get configuration from .env (raw strings — parsed in main() after validation)
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
_SOURCE_IDS_RAW = os.getenv('SOURCE_NETWORK_IDS')
_TARGET_ID_RAW = os.getenv('TARGET_NETWORK_ID')

BASE_URL = 'https://fwd.app/api'
POLL_INTERVAL = 5  # seconds between state checks
POLL_TIMEOUT = 1800  # 30 minutes
TERMINAL_STATES = frozenset({'PROCESSED', 'FAILED', 'CANCELED', 'TIMED_OUT', 'RESTORE_FAILED'})

def get_auth() -> tuple[str, str]:
    assert API_KEY is not None and API_SECRET is not None
    return (API_KEY, API_SECRET)

def get_latest_snapshot_id(network_id):
    """Get the latest processed snapshot ID for a given network"""
    url = f'{BASE_URL}/networks/{network_id}/snapshots/latestProcessed'

    print(f'Fetching latest snapshot for network {network_id}...')
    response = requests.get(url, auth=get_auth(), timeout=(10, 30))
    response.raise_for_status()

    snapshot_id = response.json().get('id')
    if snapshot_id is None:
        raise ValueError(f"No 'id' in snapshot response for network {network_id}: {response.json()}")
    print(f'  Found snapshot ID: {snapshot_id}')
    return snapshot_id

def export_snapshot(snapshot_id, download_dir='snapshots'):
    """Export a snapshot and save the zip file"""
    url = f'{BASE_URL}/snapshots/{snapshot_id}'

    Path(download_dir).mkdir(exist_ok=True)

    print(f'Exporting snapshot {snapshot_id}...')
    response = requests.get(url, auth=get_auth(), stream=True, timeout=(10, 300))
    response.raise_for_status()

    content_length = response.headers.get('Content-Length')
    total_size = int(content_length) if content_length else None

    filename = f'{download_dir}/snapshot_{snapshot_id}.zip'
    transferred = 0
    mb = 0.0
    with open(filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            transferred += len(chunk)
            mb = transferred / (1024 * 1024)
            if total_size:
                pct = transferred / total_size * 100
                print(f'\r  {mb:.1f} / {total_size / (1024 * 1024):.1f} MB ({pct:.0f}%)', end='', flush=True)
            else:
                print(f'\r  {mb:.1f} MB transferred', end='', flush=True)

    print(f'\r  Downloaded {mb:.1f} MB → {filename}' + ' ' * 10)
    return filename

def get_snapshot_state(snapshot_id):
    """Poll the processing state of a snapshot"""
    url = f'{BASE_URL}/snapshots/{snapshot_id}/metrics'
    response = requests.get(url, auth=get_auth(), timeout=(10, 30))
    response.raise_for_status()
    return response.json().get('snapshotState', 'UNKNOWN')

class _UploadProgress:
    """Wraps a file to track cumulative upload progress across all parts."""
    def __init__(self, f, counter):
        self._f = f
        self._counter = counter

    def read(self, size=-1):
        chunk = self._f.read(size)
        self._counter['sent'] += len(chunk)
        sent = self._counter['sent']
        total = self._counter['total']
        mb = sent / (1024 * 1024)
        if total:
            pct = min(sent / total * 100, 100)
            print(f'\r  Uploading {mb:.1f} / {total / (1024 * 1024):.1f} MB ({pct:.0f}%)', end='', flush=True)
        else:
            print(f'\r  Uploading {mb:.1f} MB', end='', flush=True)
        return chunk

    def __getattr__(self, name):
        return getattr(self._f, name)


def import_snapshots(network_id, snapshot_files):
    """Upload snapshots and wait for processing to complete"""
    url = f'{BASE_URL}/networks/{network_id}/snapshots'

    timestamp = datetime.now().strftime('%I:%M%p on %d %b %Y')
    note = f'Merged at {timestamp}'

    total_size = sum(os.path.getsize(f) for f in snapshot_files)
    counter = {'sent': 0, 'total': total_size}
    post_done = threading.Event()

    def show_server_wait():
        # Wait until all file bytes have been read by requests
        while not post_done.is_set() and counter['sent'] < counter['total']:
            time.sleep(0.5)
        if post_done.is_set():
            return
        # All bytes sent; server is processing before responding
        start = time.time()
        while not post_done.is_set():
            elapsed = int(time.time() - start)
            print(f'\r  Bytes sent, server processing... ({elapsed // 60}m {elapsed % 60:02d}s)', end='', flush=True)
            time.sleep(1)

    print(f'\nUploading {len(snapshot_files)} snapshots to network {network_id}...')

    wait_thread = threading.Thread(target=show_server_wait, daemon=True)
    wait_thread.start()

    try:
        with contextlib.ExitStack() as stack:
            files = [('file', (os.path.basename(f),
                               _UploadProgress(stack.enter_context(open(f, 'rb')), counter),
                               'application/zip'))
                     for f in snapshot_files]
            response = requests.post(url, auth=get_auth(), files=files, data={'note': note}, timeout=(10, POLL_TIMEOUT))
            response.raise_for_status()
            snapshot_data = response.json()
    finally:
        post_done.set()

    wait_thread.join(timeout=1)
    print(f'\r  Upload complete. Note: {note}' + ' ' * 40)

    snapshot_id = snapshot_data.get('id')
    if snapshot_id is None:
        print('  Warning: no snapshot ID in response; cannot poll processing state.')
        return snapshot_data

    print(f'  Snapshot ID: {snapshot_id}')
    last_state = None
    deadline = time.time() + POLL_TIMEOUT
    start = time.time()

    while time.time() < deadline:
        state = get_snapshot_state(snapshot_id)
        elapsed = int(time.time() - start)
        elapsed_str = f'{elapsed // 60}m {elapsed % 60:02d}s'

        if state != last_state:
            if last_state is not None:
                print()  # end the previous \r line before printing the new state
            print(f'  State: {state}', end='', flush=True)
            last_state = state
        else:
            print(f'\r  State: {state} ({elapsed_str})', end='', flush=True)

        if state in TERMINAL_STATES:
            print()
            if state != 'PROCESSED':
                raise RuntimeError(f'Import ended with state: {state}')
            print(f'  View snapshot: https://fwd.app/?/search?networkId={network_id}&snapshotId={snapshot_id}')
            return snapshot_data

        time.sleep(POLL_INTERVAL)

    print()
    raise TimeoutError(f'Import did not reach a terminal state within {POLL_TIMEOUT // 60} minutes. Last state: {last_state}')

def main():
    print('=== Forward Networks Snapshot Merger ===\n')

    # Validate configuration before any casting
    if not API_KEY or not API_SECRET:
        raise ValueError('API_KEY and API_SECRET must be set in .env file')
    if not _SOURCE_IDS_RAW:
        raise ValueError('SOURCE_NETWORK_IDS must be set in .env file')
    if _TARGET_ID_RAW is None:
        raise ValueError('TARGET_NETWORK_ID must be set in .env file')

    source_network_ids = [int(sid.strip()) for sid in _SOURCE_IDS_RAW.split(',')]
    target_network_id = int(_TARGET_ID_RAW)

    print(f'Source networks: {source_network_ids}')
    print(f'Target network: {target_network_id}\n')

    # Step 1: Get latest snapshot IDs
    snapshot_ids = []
    for network_id in source_network_ids:
        try:
            snapshot_id = get_latest_snapshot_id(network_id)
            snapshot_ids.append(snapshot_id)
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f'  Error fetching snapshot for network {network_id}: {e}')

    if len(snapshot_ids) < len(source_network_ids):
        print(f'\nFailed to fetch all snapshot IDs ({len(snapshot_ids)}/{len(source_network_ids)}). Aborting to avoid partial merge.')
        return

    print(f'\nFound {len(snapshot_ids)} snapshots to export.\n')

    # Step 2: Export all snapshots
    downloaded_files = []
    for snapshot_id in snapshot_ids:
        try:
            filename = export_snapshot(snapshot_id)
            downloaded_files.append(filename)
        except requests.exceptions.RequestException as e:
            print(f'  Error exporting snapshot {snapshot_id}: {e}')

    if len(downloaded_files) < len(snapshot_ids):
        print(f'\nFailed to export all snapshots ({len(downloaded_files)}/{len(snapshot_ids)}). Aborting to avoid partial merge.')
        return

    print(f'\nExported {len(downloaded_files)} snapshots.\n')

    # Step 3: Upload and wait for processing
    try:
        import_snapshots(target_network_id, downloaded_files)
        print(f'\n=== Import Complete ===')
    except (requests.exceptions.RequestException, RuntimeError, TimeoutError) as e:
        print(f'\nError importing snapshots: {e}')
        if isinstance(e, requests.exceptions.RequestException) and e.response is not None:
            print(f'Response: {e.response.text}')

if __name__ == '__main__':
    main()
