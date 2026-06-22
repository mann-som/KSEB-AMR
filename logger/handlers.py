import json
from datetime import datetime
from . import config

class JSONFileHandler:
    def __init__(self, filename):
        self.filename = filename

    def write(self, payload):
        file_path = config.get_log_file_path(
            filename=self.filename
        )

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
