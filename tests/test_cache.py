# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the cache abstraction layer (InMemoryBackend + Cache wrapper)."""
import time


class TestInMemoryBackend:
    def setup_method(self):
        from server.cache import _InMemoryBackend
        self.backend = _InMemoryBackend()

    def test_get_missing_key(self):
        assert self.backend.get("missing") is None

    def test_set_and_get(self):
        self.backend.set("key1", "value1")
        assert self.backend.get("key1") == "value1"

    def test_set_with_ttl_expires(self):
        self.backend.set("key1", "value1", ttl=1)
        assert self.backend.get("key1") == "value1"
        time.sleep(1.1)
        assert self.backend.get("key1") is None

    def test_delete(self):
        self.backend.set("key1", "value1")
        assert self.backend.delete("key1") is True
        assert self.backend.get("key1") is None

    def test_delete_missing(self):
        assert self.backend.delete("nope") is False

    def test_keys_all(self):
        self.backend.set("a", "1")
        self.backend.set("b", "2")
        assert sorted(self.backend.keys()) == ["a", "b"]

    def test_keys_prefix(self):
        self.backend.set("noba:x", "1")
        self.backend.set("noba:y", "2")
        self.backend.set("other", "3")
        result = self.backend.keys("noba:*")
        assert sorted(result) == ["noba:x", "noba:y"]

    def test_keys_excludes_expired(self):
        self.backend.set("live", "1", ttl=60)
        self.backend.set("dead", "2", ttl=1)
        time.sleep(1.1)
        assert self.backend.keys() == ["live"]

    def test_keys_prefix_excludes_expired(self):
        self.backend.set("noba:live", "1", ttl=60)
        self.backend.set("noba:dead", "2", ttl=1)
        time.sleep(1.1)
        assert self.backend.keys("noba:*") == ["noba:live"]

    def test_incr_new_key(self):
        assert self.backend.incr("counter") == 1

    def test_incr_existing(self):
        self.backend.set("counter", "5")
        assert self.backend.incr("counter") == 6

    def test_incr_multiple(self):
        self.backend.incr("c")
        self.backend.incr("c")
        assert self.backend.incr("c") == 3

    def test_expire(self):
        self.backend.set("key1", "val")
        self.backend.expire("key1", 1)
        assert self.backend.get("key1") == "val"
        time.sleep(1.1)
        assert self.backend.get("key1") is None

    def test_expire_missing_key_is_noop(self):
        # Should not raise
        self.backend.expire("nonexistent", 10)

    def test_flush(self):
        self.backend.set("a", "1")
        self.backend.set("b", "2")
        self.backend.flush()
        assert self.backend.keys() == []

    def test_cleanup_removes_expired(self):
        self.backend.set("live", "yes", ttl=60)
        self.backend.set("dead", "no", ttl=1)
        time.sleep(1.1)
        self.backend.cleanup()
        assert self.backend.get("live") == "yes"
        assert self.backend.get("dead") is None

    def test_cleanup_keeps_no_ttl_entries(self):
        self.backend.set("permanent", "val")
        self.backend.cleanup()
        assert self.backend.get("permanent") == "val"

    def test_is_not_redis(self):
        assert self.backend.is_redis is False

    def test_set_overwrites_existing(self):
        self.backend.set("key", "old")
        self.backend.set("key", "new")
        assert self.backend.get("key") == "new"

    def test_set_without_ttl_does_not_expire(self):
        self.backend.set("key", "val")
        # expires_at should be 0 (falsy), meaning never expires
        entry = self.backend._store.get("key")
        assert entry is not None
        assert entry[1] == 0


class TestCache:
    def setup_method(self):
        from server.cache import Cache
        self.cache = Cache()

    def test_json_roundtrip_dict(self):
        self.cache.set("test", {"a": 1, "b": [2, 3]})
        result = self.cache.get("test")
        assert result == {"a": 1, "b": [2, 3]}

    def test_json_roundtrip_list(self):
        self.cache.set("test", [1, 2, 3])
        assert self.cache.get("test") == [1, 2, 3]

    def test_json_roundtrip_string(self):
        self.cache.set("test", "hello")
        assert self.cache.get("test") == "hello"

    def test_json_roundtrip_number(self):
        self.cache.set("test", 42)
        assert self.cache.get("test") == 42

    def test_json_roundtrip_float(self):
        self.cache.set("test", 3.14)
        assert self.cache.get("test") == 3.14

    def test_json_roundtrip_bool(self):
        self.cache.set("test", True)
        assert self.cache.get("test") is True

    def test_json_roundtrip_null(self):
        self.cache.set("test", None)
        assert self.cache.get("test") is None

    def test_json_roundtrip_nested(self):
        data = {"users": [{"name": "alice", "active": True}], "count": 1}
        self.cache.set("test", data)
        assert self.cache.get("test") == data

    def test_get_missing(self):
        assert self.cache.get("missing") is None

    def test_raw_set_and_get(self):
        self.cache.set_raw("raw", "plain text")
        assert self.cache.get_raw("raw") == "plain text"

    def test_raw_get_missing(self):
        assert self.cache.get_raw("missing") is None

    def test_get_raw_bypasses_json(self):
        self.cache.set("test", {"a": 1})
        raw = self.cache.get_raw("test")
        assert isinstance(raw, str)
        assert raw == '{"a": 1}'

    def test_get_falls_back_for_non_json_raw(self):
        # If raw value is not valid JSON, .get() returns the raw string
        self.cache.set_raw("test", "not json {{{")
        result = self.cache.get("test")
        assert result == "not json {{{"

    def test_delete(self):
        self.cache.set("x", "y")
        assert self.cache.delete("x") is True
        assert self.cache.get("x") is None

    def test_delete_missing(self):
        assert self.cache.delete("nope") is False

    def test_is_not_redis_by_default(self):
        assert self.cache.is_redis is False

    def test_ttl(self):
        self.cache.set("temp", "val", ttl=1)
        assert self.cache.get("temp") == "val"
        time.sleep(1.1)
        assert self.cache.get("temp") is None

    def test_raw_ttl(self):
        self.cache.set_raw("temp", "raw", ttl=1)
        assert self.cache.get_raw("temp") == "raw"
        time.sleep(1.1)
        assert self.cache.get_raw("temp") is None

    def test_keys(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        assert sorted(self.cache.keys()) == ["a", "b"]

    def test_keys_pattern(self):
        self.cache.set("noba:x", 1)
        self.cache.set("noba:y", 2)
        self.cache.set("other", 3)
        assert sorted(self.cache.keys("noba:*")) == ["noba:x", "noba:y"]

    def test_incr(self):
        assert self.cache.incr("counter") == 1
        assert self.cache.incr("counter") == 2

    def test_expire(self):
        self.cache.set("key", "val")
        self.cache.expire("key", 1)
        assert self.cache.get("key") == "val"
        time.sleep(1.1)
        assert self.cache.get("key") is None

    def test_cleanup(self):
        self.cache.set("live", "yes", ttl=60)
        self.cache.set("dead", "no", ttl=1)
        time.sleep(1.1)
        self.cache.cleanup()
        assert self.cache.get("live") == "yes"
        assert self.cache.get("dead") is None
