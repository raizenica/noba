# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the metrics module: validators, cache, ANSI stripping, formatters."""
from server.metrics import (
    validate_ip, validate_service_name, strip_ansi, human_bps,
    TTLCache, _fmt_bytes,
)


class TestValidateIP:
    def test_valid_ipv4(self):
        assert validate_ip("192.168.1.1")
        assert validate_ip("10.0.0.1")
        assert validate_ip("255.255.255.255")

    def test_valid_ipv6(self):
        assert validate_ip("::1")
        assert validate_ip("fe80::1")

    def test_invalid(self):
        assert not validate_ip("not.an.ip")
        assert not validate_ip("")
        assert not validate_ip("999.999.999.999")
        assert not validate_ip("1.2.3")


class TestValidateServiceName:
    def test_valid(self):
        assert validate_service_name("nginx.service")
        assert validate_service_name("ssh")
        assert validate_service_name("noba-web@user")
        assert validate_service_name("my_service.timer")

    def test_invalid(self):
        assert not validate_service_name("")
        assert not validate_service_name("foo bar")
        assert not validate_service_name("../etc/passwd")
        assert not validate_service_name("rm -rf /")
        assert not validate_service_name("svc;whoami")


class TestStripAnsi:
    def test_removes_color_codes(self):
        s = "\033[0;32m[INFO]\033[0m Hello world"
        assert strip_ansi(s) == "[INFO] Hello world"

    def test_passthrough_plain(self):
        assert strip_ansi("plain text") == "plain text"

    def test_empty(self):
        assert strip_ansi("") == ""


class TestHumanBps:
    def test_bytes(self):
        assert "B/s" in human_bps(500)

    def test_kilobytes(self):
        assert "KB/s" in human_bps(2048)

    def test_megabytes(self):
        assert "MB/s" in human_bps(5 * 1024 * 1024)

    def test_zero(self):
        assert human_bps(0) == "0.0 B/s"


class TestFmtBytes:
    def test_bytes(self):
        assert _fmt_bytes(500) == "500.0B"

    def test_kilobytes(self):
        assert "KB" in _fmt_bytes(2048)

    def test_megabytes(self):
        assert "MB" in _fmt_bytes(5 * 1024 * 1024)

    def test_negative(self):
        result = _fmt_bytes(-1024)
        assert "KB" in result


class TestTTLCache:
    def test_miss(self):
        cache = TTLCache()
        assert cache.get("missing") is None

    def test_set_and_get(self):
        cache = TTLCache()
        cache.set("key", "value")
        assert cache.get("key", ttl=60) == "value"

    def test_expired(self):
        cache = TTLCache()
        cache.set("key", "value")
        assert cache.get("key", ttl=0) is None

    def test_max_size_evicts(self):
        cache = TTLCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # should evict "a"
        assert cache.get("a", ttl=60) is None
        assert cache.get("c", ttl=60) == 3

    def test_bust(self):
        cache = TTLCache()
        cache.set("container_ps", "data")
        cache.set("container_stats", "data2")
        cache.set("other", "data3")
        cache.bust("container")
        assert cache.get("container_ps", ttl=60) is None
        assert cache.get("other", ttl=60) == "data3"
