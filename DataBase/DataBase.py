import os
import threading
import contextlib
from typing import Dict, Any, Optional

import yaml

from logger import Logger

logger = Logger("DB")

class _Adapter:

    def __init__(self, db_config):
        self.config = db_config
    
    def connect(self):
        raise NotImplementedError
    
    def placeholder_style(self):

        raise NotImplementedError
    

class _MySQLAdapter(_Adapter):
    def connect(self):
        try:
            import mysql.connector
        except ImportError as ex:
            raise ImportError(
                "mysql-connector-python is required for type: mysql. "
                "Install with: pip3 install mysql-connector-python"
            ) from ex
        
        cfg = self.config

        kwargs = {
            "host" : cfg["host"],
            "port" : cfg.get("port", 3306),
            "user":     cfg["user"],
            "password": cfg["password"],
            "database": cfg["database"],
        }

        if "connect_timeout" in cfg:
            kwargs["connection_timeout"] = cfg["connect_timeout"]
        if "pool_name" in cfg:
            kwargs["pool_name"] = cfg["pool_name"]
            kwargs["pool_size"] = cfg.get("pool_size", 5)

        return mysql.connector.connect(**kwargs)
    
    def placeholder_style(self):
        return "%s"
    

class _SQLiteAdapter(_Adapter):

    def connect(self):
        import sqlite3

        cfg = self.config
        path = cfg["path"]

        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        
        conn = sqlite3.connect(
            path,
            timeout=cfg.get("timeout", 10),
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn
    
    def placeholder_style(self):
        return "?"
    
_ADAPTERS = {
    "mysql":  _MySQLAdapter,
    "sqlite": _SQLiteAdapter,
}

class Database:

    def __init__(self, name, db_config):
        
        self.name = name
        self.config = dict(db_config)
        db_type = self.config.get("type", "").lower()

        if db_type not in _ADAPTERS:
            raise ValueError(
                "Unknown db type '{}' for '{}'. Supported: {}".format(
                    db_type, name, list(_ADAPTERS.keys())
                )
            )
        
        self.db_type = db_type
        self._adapter = _ADAPTERS[db_type](self.config)
    
    @contextlib.contextmanager
    def cursor(self):
        
        conn = None
        cur = None

        try:
            conn = self._adapter.connect()
            cur = conn.cursor()

            yield cur
            conn.commit()

        except Exception:
            if conn is not None:
                try:
                    conn.rollback()

                except Exception:
                    logger.error(f"{self.name} : rollback failed", to_file=True)

            logger.error(f"{self.name} : query failed, rolled back", to_file=True)
            raise

        finally:
            if cur is not None:
                try:
                    cur.close()

                except Exception:
                    pass
            
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    
    def __repr__(self):
        safe_cfg = {k: v for k, v in self.config.items() if k != "password"}
        return "Database(name={!r}, type={!r}, config={!r})".format(
            self.name, self.db_type, safe_cfg
        )
    
class _DatabaseRegistry:

    def __init__(self):
        self._lock = threading.Lock()
        self._raw_config = None
        self._instances = {}
        self._config_path = None
    
    def configure(self, config_path):

        with self._lock:
            self._config_path = config_path
            self._raw_config = None
            self._instances = {}

    def _default_path(self):
        
        env_path = os.environ.get("DB_CONFIG_PATH")
        if env_path:
            return env_path
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    
    def _load(self):
        path = self._config_path or self._default_path()
        if not os.path.isfile(path):
            raise FileNotFoundError(
                "Database config not found at '{}'. Set DB_CONFIG_PATH env var "
                "or call configure(path) before first use.".format(path)
            )
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError("Database config at '{}' must be a YAML mapping".format(path))
        self._raw_config = raw
        logger.info(
            "[database] Loaded config from {} ({} logical DBs)".format(path, len(raw))
        )
    
    def get(self, name):
        
        with self._lock:
            if self._raw_config is None:
                self._load()
 
            if name in self._instances:
                return self._instances[name]
 
            if name not in self._raw_config:
                raise KeyError(
                    "No database config found for '{}'. Available: {}".format(
                        name, list(self._raw_config.keys())
                    )
                )
 
            db = Database(name, self._raw_config[name])
            self._instances[name] = db
            return db
        
    def reload(self):
        
        with self._lock:
            self._raw_config = None
            self._instances = {}


_registry = _DatabaseRegistry()

def configure(config_path):

    _registry.configure(config_path)


def get_database(name):

    return _registry.get(name)


def reload_config():

    _registry.reload()