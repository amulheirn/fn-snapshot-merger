import importlib.util
import os
import queue
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_from_directory, stream_with_context

app = Flask(__name__)

_script_path = Path(__file__).parent / 'fn-snapshot-merger.py'
_spec = importlib.util.spec_from_file_location('fn_snapshot_merger', _script_path)

_job_lock = threading.Lock()
_job_queue = None
_job_running = False


class _CaptureStream:
    """Captures all stdout writes during a job run and routes them to the SSE queue."""

    def __init__(self, fallback, out_queue):
        self._fallback = fallback
        self._queue = out_queue
        self._buf = ''

    def write(self, s):
        self._buf += s
        while True:
            ni = self._buf.find('\n')
            ri = self._buf.find('\r')
            if ni == -1 and ri == -1:
                break
            if ri != -1 and (ni == -1 or ri < ni):
                line = self._buf[:ri]
                self._buf = self._buf[ri + 1:]
                if line.strip():
                    self._queue.put(('progress', line.strip()))
            else:
                line = self._buf[:ni]
                self._buf = self._buf[ni + 1:]
                self._queue.put(('line', line.rstrip()))

    def flush(self):
        self._fallback.flush()


@app.route('/logo')
def logo():
    return send_from_directory('templates', 'forward_logo.png')


@app.route('/')
def index():
    load_dotenv(override=True)
    return render_template('index.html',
                           source_ids=os.getenv('SOURCE_NETWORK_IDS', ''),
                           target_id=os.getenv('TARGET_NETWORK_ID', ''),
                           has_credentials=bool(os.getenv('API_KEY') and os.getenv('API_SECRET')))


@app.route('/run', methods=['POST'])
def run():
    global _job_queue, _job_running

    with _job_lock:
        if _job_running:
            return jsonify({'error': 'A merge is already running'}), 409

        source_ids = request.form.get('source_ids', '').strip()
        target_id = request.form.get('target_id', '').strip()
        api_key = request.form.get('api_key', '').strip()
        api_secret = request.form.get('api_secret', '').strip()

        if not source_ids or not target_id:
            return jsonify({'error': 'Source IDs and target ID are required'}), 400

        if api_key:
            os.environ['API_KEY'] = api_key
        if api_secret:
            os.environ['API_SECRET'] = api_secret

        if not os.getenv('API_KEY') or not os.getenv('API_SECRET'):
            return jsonify({'error': 'API credentials are required. Enter your API key and secret in the form.'}), 400

        os.environ['SOURCE_NETWORK_IDS'] = source_ids
        os.environ['TARGET_NETWORK_ID'] = target_id

        _job_queue = queue.Queue()
        _job_running = True

    def _run():
        global _job_running
        old_stdout = sys.stdout
        capture = _CaptureStream(sys.__stdout__, _job_queue)
        sys.stdout = capture
        try:
            mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(mod)
            mod.main()
        except Exception as e:
            _job_queue.put(('error', f'ERROR: {e}'))
        finally:
            sys.stdout = old_stdout
            _job_running = False
            _job_queue.put(None)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started'})


@app.route('/stream')
def stream():
    def generate():
        q = _job_queue
        if q is None:
            return
        while True:
            item = q.get()
            if item is None:
                yield 'event: done\ndata: \n\n'
                break
            event_type, line = item
            safe = line.replace('\n', ' ')
            yield f'event: {event_type}\ndata: {safe}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/status')
def status():
    return jsonify({'running': _job_running})


if __name__ == '__main__':
    app.run(debug=False, threaded=True)
