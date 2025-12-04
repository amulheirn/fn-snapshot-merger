# Forward Networks Snapshot Merger
Andrew Mulheirn - Forward Networks - 4th December 2025

A Python script to automatically export snapshots from multiple source networks and import them into a single target network.

## Prerequisites

- Objects in the source networks must be unique.  For example 'router1' cannot exist in both source networks.
- Python 3.6 or higher
- Forward Networks API credentials (key and secret)
- Access to source and target networks

## Installation

1. Clone or download this repository

2. Install required dependencies:
```bash
pip install requests python-dotenv
```

or 
```
pip install -r requirements.txt
```


3. Create a `.env` file in the same directory as the script:
```env
API_KEY=your_api_key_here
API_SECRET=your_api_secret_here
SOURCE_NETWORK_IDS=123,456,789
TARGET_NETWORK_ID=999
```

Make sure to restrict access to the .env file:
```
chmod 600 /path/to/.env
```

### Configuration Details

- **API_KEY**: Your Forward Networks API key
- **API_SECRET**: Your Forward Networks API secret
- **SOURCE_NETWORK_IDS**: Comma-separated list of source network IDs (integers)
- **TARGET_NETWORK_ID**: The target network ID where snapshots will be imported (integer)

Details on how to generate an API key are here: https://docs.fwd.app/latest/application/settings/personal/account/#api-tokens

## Usage

### Manual Execution

Run the script directly:
```bash
python fn-snapshot-merger.py
```

### Output

The script will:
1. Create a `snapshots/` directory to store downloaded files
2. Display progress for each step (fetch, export, import)
3. Add a timestamped note to the import (e.g., "Merged at 10:30AM on 03 Dec 2025")

## Setting Up as a Cron Job

### Linux/macOS

1. Open your crontab for editing:
```bash
crontab -e
```

2. Add a line based on your scheduling needs - here are two examples:

**Run every day at 2:00 AM:**
```cron
0 2 * * * cd /path/to/script && /usr/bin/python3 fn-snapshot-merger.py >> /path/to/logs/snapshot_merge.log 2>&1
```

**Run every 2 hours:**
```cron
0 */2 * * * cd /path/to/script && /usr/bin/python3 fn-snapshot-merger.py >> /path/to/logs/snapshot_merge.log 2>&1
```

3. Save and exit the editor

### Important Notes for Cron Setup

- Replace `/path/to/script` with the actual path to your script directory
- Replace `/usr/bin/python3` with your Python path (find it with `which python3`)
- Create the logs directory: `mkdir -p /path/to/logs`
- Ensure the `.env` file is in the same directory as the script
- Make sure the script has execute permissions: `chmod +x fn-snapshot-merger.py`


### Verify Cron Job

List your current cron jobs:
```bash
crontab -l
```

Check cron logs (location varies by system):
```bash
# Ubuntu/Debian
grep CRON /var/log/syslog

# CentOS/RHEL
grep CRON /var/log/cron

# macOS
log show --predicate 'process == "cron"' --last 1h
```

### Windows Task Scheduler

1. Open Task Scheduler
2. Click "Create Basic Task"
3. Name it "Forward Networks Snapshot Merger"
4. Choose trigger (Daily, Weekly, etc.)
5. Set the time
6. Choose "Start a program"
7. Program/script: `C:\Python3\python.exe` (or your Python path)
8. Arguments: `fn-snapshot-merger.py`
9. Start in: `C:\path\to\script\directory`
10. Finish and enable the task

## Troubleshooting

### Permission Errors
Ensure the script has write permissions in its directory to create the `snapshots/` folder:
```bash
chmod +x fn-snapshot-merger.py
chmod 755 /path/to/script
```

### API Authentication Errors
- Verify your API_KEY and API_SECRET in the `.env` file
- Ensure there are no extra spaces or quotes around the values
- Check that your credentials have access to all specified networks

### Network ID Errors
- Verify all network IDs exist and are accessible with your credentials
- Ensure SOURCE_NETWORK_IDS is comma-separated with no spaces: `123,456,789`

### Cron Not Running
- Check that the full paths are used in the cron command
- Verify the `.env` file is in the correct location
- Check cron logs for error messages
- Test the script manually first to ensure it works

## Log Monitoring

To monitor your automated runs:
```bash
# View the last 50 lines of the log
tail -50 /path/to/logs/snapshot_merge.log

# Follow the log in real-time
tail -f /path/to/logs/snapshot_merge.log
```

## Support
This project is licensed under the terms of the MIT License. See LICENSE file for details.

For issues with the Forward Networks API, consult the [Forward Networks API documentation](https://docs.fwd.app/latest/api-doc/index.html).