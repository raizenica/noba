import sqlite3
import threading
import json
import os
from pathlib import Path

DB_PATH = Path(os.path.expanduser("~/.local/share/noba-history.db"))

class Database:
    _instance = None
    _lock = threading.RLock()  # <--- CHANGED TO RLock!

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Database, cls).__new__(cls)
                cls._instance._init_db()
            return cls._instance

    def _init_db(self):
        # check_same_thread=False allows FastAPI's async threadpool to share the connection safely
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER,
                    cpu_percent REAL,
                    memory_percent REAL,
                    memory_used_gb REAL,
                    disks_json TEXT,
                    net_sent INTEGER,
                    net_recv INTEGER,
                    temps_json TEXT
                )
            ''')
            self.conn.commit()

    def insert_metrics(self, data: dict):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO metrics (
                    timestamp, cpu_percent, memory_percent, memory_used_gb,
                    disks_json, net_sent, net_recv, temps_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data["timestamp"],
                data["cpu_percent"],
                data["memory_percent"],
                data["memory_used_gb"],
                json.dumps(data.get("disks", [])),
                data["network"]["bytes_sent"],
                data["network"]["bytes_recv"],
                json.dumps(data.get("temperatures", {}))
            ))
            self.conn.commit()

# Export a global safe instance
db = Database()
