import logging
from datetime import datetime
from .handlers import JSONFileHandler
from . import config


class Logger:
    LEVELS = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    def __init__(self, name="app_logger"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        config.ensureLogDir()

        self.stats_handler = JSONFileHandler(config.STATS_LOG_FILE)
        self.errors_handler = JSONFileHandler(config.ERRORS_LOG_FILE)
        self.meter_handler = JSONFileHandler(config.METER_LOG_FILE)

        self.file_handlers = {
            "stats": self.stats_handler,
            "errors": self.errors_handler,
            "meters": self.meter_handler,
        }

        self.stats = {
            "meters_processed": 0,
            "meters_success": 0,
            "meters_failed": 0,
        }

    def _normalize_targets(self, targets, to_file, level_name):
        selected = set()

        if targets is not None:
            if isinstance(targets, str):
                selected.add(targets)
            else:
                selected.update(targets)
        elif not to_file:
            selected.add("console")

        if to_file:
            if isinstance(to_file, str):
                selected.add(to_file)
            elif isinstance(to_file, (list, tuple)):
                selected.update(to_file)
            elif to_file is True:
                selected.add("console")
                if level_name in ("ERROR", "WARNING", "CRITICAL"):
                    selected.update(["errors", "meters"])
                else:
                    selected.add("meters")

        valid_targets = {"console", "stats", "errors", "meters"}
        return [target for target in selected if target in valid_targets]

    def _make_payload(self, level, message, meter_id=None, extra=None):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "app" : self.logger.name,
            "level": level,
            "message": message,
        }

        if meter_id is not None:
            payload["meter_id"] = meter_id
        if extra is not None:
            payload["extra"] = extra

        return payload

    def _write_file(self, target, payload):
        handler = self.file_handlers.get(target)
        if handler:
            handler.write(payload)

    def log(self, level, message, targets=None, to_file=False, meter_id=None, extra=None):
        level_name = level.upper() if isinstance(level, str) else "INFO"
        if level_name not in self.LEVELS:
            level_name = "INFO"

        selected = self._normalize_targets(targets, to_file, level_name)
        payload = self._make_payload(level_name, message, meter_id=meter_id, extra=extra)

        if "console" in selected:
            self.logger.log(self.LEVELS[level_name], message)

        if "errors" in selected and level_name in ("ERROR", "WARNING", "CRITICAL"):
            self._write_file("errors", payload)

        if "meters" in selected:
            self._write_file("meters", payload)

        if "stats" in selected:
            stats_payload = payload.copy()
            stats_payload["stats"] = self.stats.copy()
            self._write_file("stats", stats_payload)

    def info(self, message, targets=None, to_file=False, meter_id=None, extra=None):
        self.log("INFO", message, targets=targets, to_file=to_file, meter_id=meter_id, extra=extra)

    def warning(self, message, targets=None, to_file=False, meter_id=None, extra=None):
        self.log("WARNING", message, targets=targets, to_file=to_file, meter_id=meter_id, extra=extra)

    def error(self, message, targets=None, to_file=False, meter_id=None, extra=None):
        self.log("ERROR", message, targets=targets, to_file=to_file, meter_id=meter_id, extra=extra)

    def debug(self, message, targets=None, to_file=False, meter_id=None, extra=None):
        self.log("DEBUG", message, targets=targets, to_file=to_file, meter_id=meter_id, extra=extra)

    def record_meter_result(self, meter_id, success, message=None, details=None, targets=None, to_file=False, extra=None):
        self.stats["meters_processed"] += 1
        if success:
            self.stats["meters_success"] += 1
        else:
            self.stats["meters_failed"] += 1

        if message is None:
            status = "success" if success else "failed"
            message = f"Meter {meter_id} {status}"

        payload_extra = {"result": "success" if success else "failed"}
        if details is not None:
            payload_extra["details"] = details
        if extra is not None:
            payload_extra.update(extra)

        self.log(
            "INFO",
            message,
            targets=targets or ["stats", "meters"],
            to_file=to_file,
            meter_id=meter_id,
            extra=payload_extra,
        )

    def write_stats(self, message, extra=None, targets=None):
        self.log("INFO", message, targets=targets or ["stats"], to_file=False, meter_id=None, extra=extra)
