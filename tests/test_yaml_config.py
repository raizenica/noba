# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for YAML config read/write and caching."""
import os

import yaml

from server.yaml_config import (
    _bust_settings_cache,
    read_yaml_settings,
    write_yaml_settings,
)
from server.config import NOBA_YAML


class TestReadDefaults:
    def test_returns_defaults_when_no_file(self):
        _bust_settings_cache()
        if os.path.exists(NOBA_YAML):
            os.unlink(NOBA_YAML)
        cfg = read_yaml_settings()
        assert cfg["wanTestIp"] == "8.8.8.8"
        assert cfg["piholeUrl"] == ""
        assert cfg["backupSources"] == []

    def test_reads_web_keys(self):
        _bust_settings_cache()
        os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
        with open(NOBA_YAML, "w") as f:
            yaml.dump({"web": {"piholeUrl": "http://pi.local"}}, f)
        cfg = read_yaml_settings()
        assert cfg["piholeUrl"] == "http://pi.local"

    def test_reads_backup_section(self):
        _bust_settings_cache()
        os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
        with open(NOBA_YAML, "w") as f:
            yaml.dump({"backup": {"sources": ["/data"], "dest": "/nas"}}, f)
        cfg = read_yaml_settings()
        assert cfg["backupSources"] == ["/data"]
        assert cfg["backupDest"] == "/nas"


    def test_reads_backup_config_keys(self):
        _bust_settings_cache()
        os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
        with open(NOBA_YAML, "w") as f:
            yaml.dump({"backup": {
                "sources": ["/home", "/data"],
                "dest": "/mnt/nas",
                "retention_days": 14,
                "keep_count": 3,
                "verify_sample": 50,
                "max_delete": "1000",
                "email": "admin@test.com",
            }}, f)
        cfg = read_yaml_settings()
        assert cfg["backupSources"] == ["/home", "/data"]
        assert cfg["backupDest"] == "/mnt/nas"
        assert cfg["backupRetentionDays"] == 14
        assert cfg["backupKeepCount"] == 3
        assert cfg["backupVerifySample"] == 50
        assert cfg["backupMaxDelete"] == "1000"
        assert cfg["backupEmail"] == "admin@test.com"

    def test_backup_defaults_when_no_file(self):
        _bust_settings_cache()
        if os.path.exists(NOBA_YAML):
            os.unlink(NOBA_YAML)
        cfg = read_yaml_settings()
        assert cfg["backupRetentionDays"] == 7
        assert cfg["backupKeepCount"] == 0
        assert cfg["backupVerifySample"] == 20
        assert cfg["backupMaxDelete"] == ""
        assert cfg["backupEmail"] == ""


class TestWriteSettings:
    def test_write_and_read_round_trip(self):
        _bust_settings_cache()
        settings = {"piholeUrl": "http://pi.local", "wanTestIp": "1.1.1.1"}
        assert write_yaml_settings(settings)
        _bust_settings_cache()
        cfg = read_yaml_settings()
        assert cfg["piholeUrl"] == "http://pi.local"
        assert cfg["wanTestIp"] == "1.1.1.1"

    def test_backup_config_round_trip(self):
        _bust_settings_cache()
        settings = {
            "backupSources": ["/home", "/var/log"],
            "backupDest": "/mnt/nas/backups",
            "backupRetentionDays": 30,
            "backupKeepCount": 5,
            "backupVerifySample": 100,
            "backupMaxDelete": "500",
            "backupEmail": "test@example.com",
            "cloudRemote": "gdrive",
            "downloadsDir": "/downloads",
        }
        assert write_yaml_settings(settings)
        _bust_settings_cache()
        # Verify YAML structure directly
        with open(NOBA_YAML) as f:
            raw = yaml.safe_load(f)
        assert raw["backup"]["sources"] == ["/home", "/var/log"]
        assert raw["backup"]["dest"] == "/mnt/nas/backups"
        assert raw["backup"]["retention_days"] == 30
        assert raw["backup"]["keep_count"] == 5
        assert raw["backup"]["verify_sample"] == 100
        assert raw["backup"]["max_delete"] == "500"
        assert raw["backup"]["email"] == "test@example.com"
        assert raw["cloud"]["remote"] == "gdrive"
        assert raw["downloads"]["dir"] == "/downloads"
        # Verify round-trip through read
        cfg = read_yaml_settings()
        assert cfg["backupRetentionDays"] == 30
        assert cfg["backupKeepCount"] == 5
        assert cfg["cloudRemote"] == "gdrive"
        assert cfg["downloadsDir"] == "/downloads"

    def test_write_preserves_backup_section(self):
        _bust_settings_cache()
        os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
        with open(NOBA_YAML, "w") as f:
            yaml.dump({"backup": {"sources": ["/data"], "dest": "/nas"}}, f)
        write_yaml_settings({"piholeUrl": "http://pi.local"})
        _bust_settings_cache()
        with open(NOBA_YAML) as f:
            raw = yaml.safe_load(f)
        assert raw["backup"]["sources"] == ["/data"]
        assert raw["backup"]["dest"] == "/nas"


class TestSettingsCache:
    def test_cache_returns_same_result(self):
        _bust_settings_cache()
        cfg1 = read_yaml_settings()
        cfg2 = read_yaml_settings()
        assert cfg1 is cfg2  # same object from cache

    def test_bust_cache_forces_reread(self):
        _bust_settings_cache()
        cfg1 = read_yaml_settings()
        _bust_settings_cache()
        cfg2 = read_yaml_settings()
        # After bust, should be a fresh dict (not the same object)
        assert cfg1 is not cfg2

    def test_write_busts_cache(self):
        _bust_settings_cache()
        cfg1 = read_yaml_settings()
        write_yaml_settings({"piholeUrl": "http://changed.local"})
        cfg2 = read_yaml_settings()
        assert cfg2["piholeUrl"] == "http://changed.local"
        assert cfg1 is not cfg2
