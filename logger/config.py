import os
from datetime import datetime, timedelta
from Config import config

STATS_LOG_FILE = "stats.jsonl"
ERRORS_LOG_FILE = "errors.jsonl"
METER_LOG_FILE = "meters.jsonl"


def ensureLogDir():
    os.makedirs(config.LOG_DIR, exist_ok=True)

def get_date_dir(date=None):
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    date_dir = os.path.join(config.LOG_DIR, date)
    os.makedirs(date_dir, exist_ok=True)

    return date_dir

def get_log_file_path(filename):
    date_dir = get_date_dir()
    return os.path.join(date_dir, filename)


