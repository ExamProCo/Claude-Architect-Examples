import os
from datetime import datetime

# Capture timestamp once at import time so the whole run shares one log file.
_RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
_log_file = None


def _get_log_file():
    global _log_file
    if _log_file is not None:
        return _log_file

    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{_RUN_TIMESTAMP}.log")
    _log_file = open(log_path, "a", encoding="utf-8")
    return _log_file


def write(text: str) -> None:
    f = _get_log_file()
    f.write(text + "\n")
    f.flush()
