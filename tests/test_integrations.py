# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for server.integrations -- all integration drivers.

Covers: base class, simple drivers, cookie-based auth (UniFi, qBittorrent),
WebSocket driver (TrueNAS), Proxmox, Pi-hole, Home Assistant, and edge cases.
"""
from __future__ import annotations

import json
import time

import httpx
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data=None, status_code=200, headers=None, text=""):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text
    resp.headers = headers or {}
    resp.cookies = MagicMock()
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


def _mock_client_ctx(mock_client_cls):
    """Wire up a mock httpx.Client class so `with Client() as c:` works."""
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


# ===========================================================================
# 1. BaseIntegration — interface, retries, caching, URL validation
# ===========================================================================

class TestBaseIntegration:
    """Base class contract tests."""

    def test_fetch_raises_not_implemented(self):
        from server.integrations.base import BaseIntegration
        bi = BaseIntegration()
        with pytest.raises(NotImplementedError):
            bi._fetch()

    def test_get_calls_fetch(self):
        from server.integrations.base import BaseIntegration

        class Concrete(BaseIntegration):
            def _fetch(self):
                return {"data": 1}

        assert Concrete().get() == {"data": 1}

    def test_default_retries_and_ttl(self):
        from server.integrations.base import BaseIntegration
        bi = BaseIntegration()
        assert bi.retries == 2
        assert bi.ttl == 0

    def test_custom_retries_and_ttl(self):
        from server.integrations.base import BaseIntegration
        bi = BaseIntegration(retries=5, ttl=30)
        assert bi.retries == 5
        assert bi.ttl == 30

    def test_validate_url_rejects_ftp(self):
        from server.integrations.base import BaseIntegration, ConfigError
        with pytest.raises(ConfigError):
            BaseIntegration.validate_url("ftp://example.com")

    def test_validate_url_rejects_file(self):
        from server.integrations.base import BaseIntegration, ConfigError
        with pytest.raises(ConfigError):
            BaseIntegration.validate_url("file:///etc/passwd")

    def test_validate_url_rejects_javascript(self):
        from server.integrations.base import BaseIntegration, ConfigError
        with pytest.raises(ConfigError):
            BaseIntegration.validate_url("javascript:alert(1)")

    def test_validate_url_accepts_http(self):
        from server.integrations.base import BaseIntegration
        assert BaseIntegration.validate_url("http://host:8080/path") == "http://host:8080/path"

    def test_validate_url_accepts_https(self):
        from server.integrations.base import BaseIntegration
        assert BaseIntegration.validate_url("https://example.com") == "https://example.com"

    def test_validate_url_strips_trailing_slash(self):
        from server.integrations.base import BaseIntegration
        assert BaseIntegration.validate_url("https://example.com/") == "https://example.com"

    def test_config_error_no_retry_on_401(self):
        from server.integrations.base import BaseIntegration, ConfigError

        class Failing(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                mock_resp = MagicMock()
                mock_resp.status_code = 401
                raise httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)

        bi = Failing(retries=3)
        with pytest.raises(ConfigError):
            bi.get()
        assert bi.call_count == 1

    def test_config_error_no_retry_on_403(self):
        from server.integrations.base import BaseIntegration, ConfigError

        class Failing(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                mock_resp = MagicMock()
                mock_resp.status_code = 403
                raise httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)

        bi = Failing(retries=3)
        with pytest.raises(ConfigError):
            bi.get()
        assert bi.call_count == 1

    def test_retries_on_408_request_timeout(self):
        """408 and 429 are retryable even though they are 4xx."""
        from server.integrations.base import BaseIntegration

        class Flaky(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                if self.call_count < 2:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 408
                    raise httpx.HTTPStatusError("408", request=MagicMock(), response=mock_resp)
                return {"ok": True}

        bi = Flaky(retries=2)
        assert bi.get() == {"ok": True}
        assert bi.call_count == 2

    def test_retries_on_429_too_many_requests(self):
        from server.integrations.base import BaseIntegration

        class Flaky(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                if self.call_count < 2:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 429
                    raise httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
                return {"ok": True}

        bi = Flaky(retries=2)
        assert bi.get() == {"ok": True}

    def test_retries_on_5xx(self):
        from server.integrations.base import BaseIntegration

        class Flaky(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                if self.call_count < 2:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 502
                    raise httpx.HTTPStatusError("502", request=MagicMock(), response=mock_resp)
                return {"ok": True}

        bi = Flaky(retries=2)
        assert bi.get() == {"ok": True}
        assert bi.call_count == 2

    def test_exhausted_retries_raises_transient_error(self):
        from server.integrations.base import BaseIntegration, TransientError

        class AlwaysFails(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                raise httpx.TimeoutException("timeout")

        bi = AlwaysFails(retries=2)
        with pytest.raises(TransientError):
            bi.get()
        assert bi.call_count == 2

    def test_retries_on_connection_error(self):
        from server.integrations.base import BaseIntegration, TransientError

        class Broken(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                raise httpx.ConnectError("refused")

        bi = Broken(retries=2)
        with pytest.raises(TransientError):
            bi.get()
        assert bi.call_count == 2

    def test_retries_on_os_error(self):
        from server.integrations.base import BaseIntegration, TransientError

        class Broken(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                raise OSError("network unreachable")

        bi = Broken(retries=2)
        with pytest.raises(TransientError):
            bi.get()
        assert bi.call_count == 2

    def test_cache_ttl_serves_cached_data(self):
        from server.integrations.base import BaseIntegration

        class Cached(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                return {"n": self.call_count}

        bi = Cached(ttl=60)
        r1 = bi.get()
        r2 = bi.get()
        assert r1 == r2 == {"n": 1}
        assert bi.call_count == 1

    def test_cache_expired_refetches(self):
        from server.integrations.base import BaseIntegration

        class Cached(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                return {"n": self.call_count}

        bi = Cached(ttl=0.01)
        bi.get()
        time.sleep(0.02)
        r2 = bi.get()
        assert bi.call_count == 2
        assert r2 == {"n": 2}

    def test_no_cache_by_default(self):
        from server.integrations.base import BaseIntegration

        class NoCached(BaseIntegration):
            call_count = 0

            def _fetch(self):
                self.call_count += 1
                return {"n": self.call_count}

        bi = NoCached()
        bi.get()
        bi.get()
        assert bi.call_count == 2


class TestSslVerify:
    def test_bool_true(self):
        from server.integrations.base import ssl_verify
        assert ssl_verify(True) is True

    def test_bool_false(self):
        from server.integrations.base import ssl_verify
        assert ssl_verify(False) is False

    def test_string_false(self):
        from server.integrations.base import ssl_verify
        assert ssl_verify("false") is False
        assert ssl_verify("0") is False
        assert ssl_verify("False") is False

    def test_string_true(self):
        from server.integrations.base import ssl_verify
        assert ssl_verify("true") is True

    @patch("os.path.isfile", return_value=True)
    def test_ca_bundle_path(self, _mock):
        from server.integrations.base import ssl_verify
        assert ssl_verify("/etc/ssl/ca-bundle.crt") == "/etc/ssl/ca-bundle.crt"


class TestSharedClient:
    def test_follow_redirects_disabled(self):
        """SSRF protection: shared client must not follow redirects."""
        from server.integrations.base import _client
        assert _client.follow_redirects is False


# ===========================================================================
# 2. Simple drivers — Plex, Kuma, TrueNAS REST, Servarr, Speedtest,
#    AdGuard, Jellyfin, Energy/Shelly, Scrutiny, Frigate, Graylog, InfluxDB
# ===========================================================================

class TestPlex:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_plex
        assert get_plex("", "token") is None

    def test_returns_none_when_no_token(self):
        from server.integrations.simple import get_plex
        assert get_plex("http://plex:32400", "") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_plex
        mock_get.side_effect = [
            {"MediaContainer": {"size": 3}},
            {"MediaContainer": {"size": 1}},
        ]
        result = get_plex("http://plex:32400", "token")
        assert result["status"] == "online"
        assert result["sessions"] == 3
        assert result["activities"] == 1

    @patch("server.integrations.simple_media._http_get")
    def test_returns_offline_on_error(self, mock_get):
        from server.integrations.simple import get_plex
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_plex("http://plex:32400", "token")
        assert result["status"] == "offline"
        assert result["sessions"] == 0


class TestKuma:
    def test_returns_empty_when_no_url(self):
        from server.integrations.simple import get_kuma
        assert get_kuma("") == []

    @patch("server.integrations.simple_monitoring._client")
    def test_parses_metrics(self, mock_client):
        from server.integrations.simple import get_kuma
        metrics_text = (
            '# HELP monitor_status\n'
            'monitor_status{monitor_name="Web"} 1\n'
            'monitor_status{monitor_name="API"} 0\n'
            'monitor_status{monitor_name="DB"} 2\n'
        )
        resp = MagicMock()
        resp.text = metrics_text
        resp.raise_for_status.return_value = None
        mock_client.get.return_value = resp
        result = get_kuma("http://kuma:3001")
        assert len(result) == 3
        assert result[0] == {"name": "Web", "status": "Up"}
        assert result[1] == {"name": "API", "status": "Down"}
        assert result[2] == {"name": "DB", "status": "Pending"}

    @patch("server.integrations.simple_monitoring._client")
    def test_returns_error_on_error(self, mock_client):
        from server.integrations.simple import get_kuma
        mock_client.get.side_effect = httpx.HTTPError("fail")
        result = get_kuma("http://kuma:3001")
        assert result["status"] == "offline"
        assert "error" in result


class TestTruenasRest:
    """Tests for the legacy REST driver in simple.py."""

    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_truenas
        assert get_truenas("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.simple import get_truenas
        assert get_truenas("http://truenas:443", "") is None

    @patch("server.integrations.simple_infra._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_truenas
        mock_get.side_effect = [
            [{"name": "plex", "state": "RUNNING"}],       # apps
            [{"level": "WARNING", "formatted": "Disk hot", "dismissed": False}],  # alerts
            [{"id": 1, "name": "testvm", "status": {"state": "RUNNING"}}],        # vms
        ]
        result = get_truenas("http://truenas:443", "apikey")
        assert result["status"] == "online"
        assert len(result["apps"]) == 1
        assert result["apps"][0]["name"] == "plex"
        assert len(result["alerts"]) == 1
        assert len(result["vms"]) == 1

    @patch("server.integrations.simple_infra._http_get")
    def test_dismissed_alerts_excluded(self, mock_get):
        from server.integrations.simple import get_truenas
        mock_get.side_effect = [
            [],
            [{"level": "WARNING", "formatted": "Old issue", "dismissed": True}],
            [],
        ]
        result = get_truenas("http://truenas:443", "apikey")
        assert result["alerts"] == []

    @patch("server.integrations.simple_infra._http_get")
    def test_returns_offline_on_error(self, mock_get):
        from server.integrations.simple import get_truenas
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_truenas("http://truenas:443", "key")
        assert result["status"] == "offline"


class TestServarr:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_servarr
        assert get_servarr("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.simple import get_servarr
        assert get_servarr("http://radarr:7878", "") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_servarr
        mock_get.return_value = {"totalRecords": 7}
        result = get_servarr("http://radarr:7878", "key")
        assert result["status"] == "online"
        assert result["queue_count"] == 7

    @patch("server.integrations.simple_media._http_get")
    def test_returns_offline_on_error(self, mock_get):
        from server.integrations.simple import get_servarr
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_servarr("http://radarr:7878", "key")
        assert result["status"] == "offline"
        assert result["queue_count"] == 0


class TestSpeedtest:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_speedtest
        assert get_speedtest("") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_speedtest
        mock_get.return_value = {
            "data": {
                "download": 100_000_000,
                "upload": 50_000_000,
                "ping": 12.5,
                "server_name": "TestServer",
            },
        }
        result = get_speedtest("http://speedtest:8080")
        assert result["status"] == "online"
        assert result["download"] == 100.0
        assert result["upload"] == 50.0
        assert result["ping"] == 12.5
        assert result["server"] == "TestServer"

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_when_no_data(self, mock_get):
        from server.integrations.simple import get_speedtest
        mock_get.return_value = {"data": None}
        assert get_speedtest("http://speedtest:8080") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_speedtest
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_speedtest("http://speedtest:8080")
        assert result["status"] == "offline"


class TestAdguard:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_adguard
        assert get_adguard("", "", "") is None

    @patch("server.integrations.simple_network._http_get")
    def test_returns_data_with_auth(self, mock_get):
        from server.integrations.simple import get_adguard
        mock_get.return_value = {"num_dns_queries": 1000, "num_blocked_filtering": 200}
        result = get_adguard("http://adguard:3000", "admin", "pass")
        assert result["status"] == "enabled"
        assert result["queries"] == 1000
        assert result["blocked"] == 200
        assert result["percent"] == 20.0

    @patch("server.integrations.simple_network._http_get")
    def test_returns_data_without_auth(self, mock_get):
        from server.integrations.simple import get_adguard
        mock_get.return_value = {"num_dns_queries": 500, "num_blocked_filtering": 0}
        result = get_adguard("http://adguard:3000", "", "")
        assert result["percent"] == 0

    @patch("server.integrations.simple_network._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_adguard
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_adguard("http://adguard:3000", "", "")
        assert result["status"] == "offline"


class TestJellyfin:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_jellyfin
        assert get_jellyfin("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.simple import get_jellyfin
        assert get_jellyfin("http://jf:8096", "") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_jellyfin
        mock_get.side_effect = [
            [{"NowPlayingItem": {"Name": "Movie"}}, {"Id": "s2"}],  # Sessions
            {"MovieCount": 50, "SeriesCount": 10, "EpisodeCount": 200},  # Counts
        ]
        result = get_jellyfin("http://jf:8096", "key")
        assert result["status"] == "online"
        assert result["streams"] == 1
        assert result["movies"] == 50
        assert result["series"] == 10
        assert result["episodes"] == 200

    @patch("server.integrations.simple_media._http_get")
    def test_returns_offline_on_error(self, mock_get):
        from server.integrations.simple import get_jellyfin
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_jellyfin("http://jf:8096", "key")
        assert result["status"] == "offline"
        assert result["streams"] == 0


class TestEnergyShelly:
    @patch("server.integrations.simple_monitoring._http_get")
    def test_gen2_success(self, mock_get):
        from server.integrations.simple import get_energy_shelly
        mock_get.return_value = {
            "apower": 125.3, "voltage": 230.1, "current": 0.545,
            "aenergy": {"total": 4500.0}, "output": True,
        }
        result = get_energy_shelly(["192.168.1.50|Kitchen Plug"])
        assert len(result) == 1
        assert result[0]["name"] == "Kitchen Plug"
        assert result[0]["status"] == "online"
        assert result[0]["power_w"] == 125.3

    @patch("server.integrations.simple_monitoring._http_get")
    def test_gen1_fallback(self, mock_get):
        from server.integrations.simple import get_energy_shelly
        # Gen2 fails, Gen1 succeeds
        mock_get.side_effect = [
            httpx.HTTPError("gen2 fail"),
            {"meters": [{"power": 80.0, "total": 600}], "relays": [{"ison": True}]},
        ]
        result = get_energy_shelly(["192.168.1.51|Office"])
        assert len(result) == 1
        assert result[0]["name"] == "Office"
        assert result[0]["status"] == "online"
        assert result[0]["power_w"] == 80.0

    @patch("server.integrations.simple_monitoring._http_get")
    def test_both_fail_offline(self, mock_get):
        from server.integrations.simple import get_energy_shelly
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_energy_shelly(["192.168.1.52|Garage"])
        assert len(result) == 1
        assert result[0]["status"] == "offline"

    def test_empty_urls(self):
        from server.integrations.simple import get_energy_shelly
        assert get_energy_shelly([]) == []


class TestScrutiny:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_scrutiny
        assert get_scrutiny("") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_scrutiny
        mock_get.return_value = {
            "data": {
                "summary": {
                    "wwn1": {
                        "device": {
                            "device_name": "sda", "model_name": "WD",
                            "serial_number": "ABC", "device_status": 0,
                            "capacity": 500_000_000_000, "device_protocol": "ATA",
                        },
                        "smart": {"temp": 35, "power_on_hours": 10000},
                    },
                    "wwn2": {
                        "device": {
                            "device_name": "sdb", "model_name": "Seagate",
                            "serial_number": "DEF", "device_status": 2,
                            "capacity": 1_000_000_000_000, "device_protocol": "ATA",
                        },
                        "smart": {"temp": 42, "power_on_hours": 20000},
                    },
                },
            },
        }
        result = get_scrutiny("http://scrutiny:8080")
        assert result["devices"] == 2
        assert result["healthy"] == 1
        assert result["failed"] == 1
        assert result["maxTemp"] == 42

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_on_empty_summary(self, mock_get):
        from server.integrations.simple import get_scrutiny
        mock_get.return_value = {"data": {"summary": {}}}
        assert get_scrutiny("http://scrutiny:8080") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_scrutiny
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_scrutiny("http://scrutiny:8080")
        assert result["status"] == "offline"


class TestFrigate:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_frigate
        assert get_frigate("") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_frigate
        mock_get.side_effect = [
            # stats
            {
                "front": {"camera_fps": 15},
                "back": {"camera_fps": 0},
                "service": {"version": "0.14.0", "uptime": 86400},
            },
            # config
            {
                "cameras": {
                    "front": {"detect": {"enabled": True}, "record": {"enabled": True}},
                    "back": {"detect": {"enabled": False}, "record": {"enabled": False}},
                },
            },
        ]
        result = get_frigate("http://frigate:5000")
        assert result["status"] == "online"
        assert result["cameraCount"] == 2
        assert result["onlineCount"] == 1
        assert result["version"] == "0.14.0"

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_frigate
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_frigate("http://frigate:5000")
        assert result["status"] == "offline"


class TestGraylog:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_graylog
        assert get_graylog("", "token") is None

    def test_returns_none_when_no_token(self):
        from server.integrations.simple import get_graylog
        assert get_graylog("http://graylog:9000", "") is None

    @patch("server.integrations.simple_monitoring._client")
    def test_returns_data_on_success(self, mock_client):
        from server.integrations.simple import get_graylog
        resp = _mock_response(json_data={
            "total_results": 42,
            "messages": [
                {"message": {"timestamp": "2026-03-24T12:00:00Z", "source": "web01",
                             "message": "Error occurred", "level": 3, "facility": "user"}},
            ],
        })
        mock_client.get.return_value = resp
        result = get_graylog("http://graylog:9000", "api-token")
        assert result["status"] == "online"
        assert result["total"] == 42
        assert len(result["messages"]) == 1

    @patch("server.integrations.simple_monitoring._client")
    def test_returns_none_on_error(self, mock_client):
        from server.integrations.simple import get_graylog
        mock_client.get.side_effect = httpx.HTTPError("fail")
        result = get_graylog("http://graylog:9000", "token")
        assert result["status"] == "offline"


class TestInfluxdb:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import query_influxdb
        assert query_influxdb("", "token", "org", "query") is None

    def test_returns_none_when_no_query(self):
        from server.integrations.simple import query_influxdb
        assert query_influxdb("http://influx:8086", "token", "org", "") is None

    @patch("server.integrations.simple_monitoring._client")
    def test_returns_parsed_csv(self, mock_client):
        from server.integrations.simple import query_influxdb
        csv = "_time,_value,_field\n2026-03-24T00:00:00Z,42.5,temperature"
        resp = _mock_response(text=csv)
        resp.text = csv
        mock_client.post.return_value = resp
        result = query_influxdb("http://influx:8086", "token", "myorg", "from(bucket:...)")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_value"] == "42.5"

    @patch("server.integrations.simple_monitoring._client")
    def test_returns_none_on_error(self, mock_client):
        from server.integrations.simple import query_influxdb
        mock_client.post.side_effect = httpx.HTTPError("fail")
        result = query_influxdb("http://influx:8086", "token", "org", "query")
        assert result["status"] == "offline"


# ===========================================================================
# 3. Tautulli, Overseerr, Prowlarr, ServarrExtended, ServarrCalendar,
#    Nextcloud, Traefik, NPM, Authentik, Cloudflare, OMV, XCP-ng,
#    Homebridge, Z2M, ESPHome, PiKVM, K8s, Gitea, GitLab, GitHub,
#    Paperless, Vaultwarden, Weather (carried forward from original)
# ===========================================================================

class TestTautulli:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_tautulli
        assert get_tautulli("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.simple import get_tautulli
        assert get_tautulli("http://tautulli:8181", "") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_tautulli
        mock_get.side_effect = [
            {"response": {"data": {
                "stream_count": 2, "stream_count_direct_play": 1, "stream_count_transcode": 1,
            }}},
            {"response": {"data": [
                {"rows": [
                    {"friendly_name": "Alice", "total_plays": 100},
                    {"friendly_name": "Bob", "total_plays": 50},
                ]},
            ]}},
        ]
        result = get_tautulli("http://tautulli:8181", "apikey")
        assert result["status"] == "online"
        assert result["streams"] == 2
        assert len(result["top_users"]) == 2

    @patch("server.integrations.simple_media._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_tautulli
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_tautulli("http://tautulli:8181", "key")
        assert result["status"] == "offline"


class TestOverseerr:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_overseerr
        assert get_overseerr("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.simple import get_overseerr
        assert get_overseerr("http://overseerr:5055", "") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_overseerr
        mock_get.return_value = {"pending": 3, "approved": 10, "available": 8, "total": 21}
        result = get_overseerr("http://overseerr:5055", "apikey")
        assert result["status"] == "online"
        assert result["pending"] == 3
        assert result["total"] == 21

    @patch("server.integrations.simple_media._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_overseerr
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_overseerr("http://overseerr:5055", "apikey")
        assert result["status"] == "offline"


class TestProwlarr:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_prowlarr
        assert get_prowlarr("", "key") is None

    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_prowlarr
        mock_get.return_value = [{"id": 1}, {"id": 2}]
        result = get_prowlarr("http://prowlarr:9696", "key")
        assert result["indexer_count"] == 2

    @patch("server.integrations.simple_media._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_prowlarr
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_prowlarr("http://prowlarr:9696", "key")
        assert result["status"] == "offline"


class TestServarrExtended:
    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_servarr_extended
        mock_get.side_effect = [
            {"totalRecords": 5},
            {"totalRecords": 12},
            [{"totalSpace": 2 * 1024**3, "freeSpace": 1 * 1024**3}],
        ]
        result = get_servarr_extended("http://radarr:7878", "key", "radarr")
        assert result["queue_count"] == 5
        assert result["missing"] == 12
        assert result["service"] == "radarr"


class TestServarrCalendar:
    @patch("server.integrations.simple_media._http_get")
    def test_returns_episodes(self, mock_get):
        from server.integrations.simple import get_servarr_calendar
        mock_get.return_value = [
            {"title": "S02E05", "series": {"title": "Breaking Bad"}, "airDateUtc": "2026-03-20T00:00:00Z"},
            {"title": "The Matrix 5", "inCinemas": "2026-03-22"},
        ]
        result = get_servarr_calendar("http://sonarr:8989", "key")
        assert len(result) == 2
        assert result[0]["type"] == "episode"
        assert result[1]["type"] == "movie"


class TestNextcloud:
    @patch("server.integrations.simple_media._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.simple import get_nextcloud
        mock_get.return_value = {
            "ocs": {"data": {
                "nextcloud": {
                    "storage": {"num_files": 42000},
                    "system": {"version": "28.0.1", "freespace": 50 * 1024**3, "freespacealiased": 100 * 1024**3},
                },
                "activeUsers": {"last5minutes": 3},
            }},
        }
        result = get_nextcloud("http://nc:443", "admin", "pass")
        assert result["status"] == "online"
        assert result["active_users"] == 3


class TestTraefik:
    @patch("server.integrations.simple_network._http_get")
    def test_counts_errors(self, mock_get):
        from server.integrations.simple import get_traefik
        mock_get.side_effect = [
            [{"name": "r1"}, {"name": "r2"}],
            [{"name": "svc1", "status": "error", "serverStatus": {}},
             {"name": "svc2", "status": "enabled", "serverStatus": {"http://b:80": "DOWN"}}],
        ]
        result = get_traefik("http://traefik:8080")
        assert result["routers"] == 2
        assert result["errors"] >= 1


class TestNpm:
    @patch("server.integrations.simple_network._http_get")
    def test_returns_proxy_host_count(self, mock_get):
        from server.integrations.simple import get_npm
        mock_get.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = get_npm("http://npm:81", "jwt")
        assert result["proxy_hosts"] == 3


class TestAuthentik:
    @patch("server.integrations.simple_comms._http_get")
    def test_returns_user_and_login_counts(self, mock_get):
        from server.integrations.simple import get_authentik
        mock_get.side_effect = [
            {"pagination": {"count": 25}},
            {"pagination": {"count": 4}},
        ]
        result = get_authentik("http://authentik:9000", "token")
        assert result["users"] == 25
        assert result["failed_logins"] == 4


class TestCloudflare:
    @patch("server.integrations.simple_network._http_get")
    def test_returns_analytics(self, mock_get):
        from server.integrations.simple import get_cloudflare
        mock_get.return_value = {
            "result": {"totals": {
                "requests": {"all": 10000},
                "threats": {"all": 42},
                "bandwidth": {"all": 5 * 1024**3, "cached": 3 * 1024**3},
            }},
        }
        result = get_cloudflare("token", "zone123")
        assert result["requests"] == 10000
        assert result["cache_hit_ratio"] == 60.0


class TestOmv:
    @patch("server.integrations.simple_infra.httpx.Client")
    def test_returns_filesystems(self, mock_client_cls):
        from server.integrations.simple import get_omv
        mock_client = _mock_client_ctx(mock_client_cls)
        login_resp = _mock_response(json_data={"response": "ok"})
        fs_resp = _mock_response(json_data=[
            {"devicefile": "/dev/sda1", "label": "data", "percentage": 45.3},
        ])
        mock_client.post.side_effect = [login_resp, fs_resp]
        result = get_omv("http://omv:80", "admin", "pass")
        assert result["status"] == "online"
        assert len(result["filesystems"]) == 1


class TestXcpng:
    @patch("server.integrations.simple_infra._hypervisor_client")
    def test_filters_control_domains(self, mock_client):
        from server.integrations.simple import get_xcpng
        login_resp = _mock_response(json_data={"result": "session-id"})
        vm_resp = _mock_response(json_data={"result": {
            "ref1": {"name_label": "vm1", "power_state": "Running",
                     "is_control_domain": False, "is_a_template": False},
            "ref2": {"name_label": "dom0", "power_state": "Running",
                     "is_control_domain": True, "is_a_template": False},
        }})
        mock_client.post.side_effect = [login_resp, vm_resp]
        result = get_xcpng("http://xcp:443", "root", "pass")
        assert result["vms"] == 1
        assert result["running_vms"] == 1


class TestHomebridge:
    @patch("server.integrations.simple_iot.httpx.Client")
    def test_detects_battery_devices(self, mock_client_cls):
        from server.integrations.simple import get_homebridge
        mock_client = _mock_client_ctx(mock_client_cls)
        login_resp = _mock_response(json_data={"access_token": "jwt"})
        acc_resp = _mock_response(json_data=[
            {"serviceName": "Motion Sensor",
             "serviceCharacteristics": [{"type": "BatteryLevel", "value": 15}]},
            {"serviceName": "Light", "serviceCharacteristics": [{"type": "On", "value": True}]},
        ])
        mock_client.post.return_value = login_resp
        mock_client.get.return_value = acc_resp
        result = get_homebridge("http://hb:8581", "admin", "pass")
        assert result["accessories"] == 2
        assert len(result["battery_devices"]) == 1


class TestZ2m:
    @patch("server.integrations.simple_iot._http_get")
    def test_detects_offline_and_low_battery(self, mock_get):
        from server.integrations.simple import get_z2m
        mock_get.return_value = [
            {"friendly_name": "Sensor", "availability": {"state": "offline"},
             "battery": 10, "interview_completed": True},
            {"friendly_name": "Bulb", "availability": {"state": "online"},
             "battery": 90, "interview_completed": True},
        ]
        result = get_z2m("http://z2m:8080")
        assert result["offline"] == 1
        assert len(result["low_battery"]) == 1


class TestEsphome:
    @patch("server.integrations.simple_iot._http_get")
    def test_counts_online_nodes(self, mock_get):
        from server.integrations.simple import get_esphome
        mock_get.return_value = [
            {"name": "e1", "status": "ONLINE", "connected": True},
            {"name": "e2", "status": "OFFLINE", "connected": False},
        ]
        result = get_esphome("http://esphome:6052")
        assert result["nodes"] == 2
        assert result["online"] == 1


class TestUnifiProtect:
    @patch("server.integrations.unifi.httpx.Client")
    def test_counts_recording_cameras(self, mock_client_cls):
        from server.integrations.unifi import get_unifi_protect
        mock_client = _mock_client_ctx(mock_client_cls)
        login_resp = _mock_response(json_data={"id": "user1"})
        cam_resp = _mock_response(json_data=[
            {"name": "Front", "isRecording": True, "recordingSettings": {"mode": "always"}},
            {"name": "Back", "isRecording": False, "recordingSettings": {"mode": "never"}},
        ])
        mock_client.post.return_value = login_resp
        mock_client.get.return_value = cam_resp
        result = get_unifi_protect("http://protect:443", "admin", "pass")
        assert result["cameras"] == 2
        assert result["recording"] == 1

    def test_returns_none_when_no_url(self):
        from server.integrations.unifi import get_unifi_protect
        assert get_unifi_protect("", "admin", "pass") is None


class TestPikvm:
    @patch("server.integrations.simple_iot._http_get")
    def test_online(self, mock_get):
        from server.integrations.simple import get_pikvm
        mock_get.return_value = {"result": {}}
        result = get_pikvm("http://pikvm:443", "admin", "admin")
        assert result["status"] == "online"


class TestK8s:
    @patch("server.integrations.simple_infra._container_runtime_client")
    def test_counts_pods_and_namespaces(self, mock_client):
        from server.integrations.simple import get_k8s
        mock_client.get.return_value = _mock_response(json_data={"items": [
            {"metadata": {"name": "p1", "namespace": "default"}, "status": {"phase": "Running"}},
            {"metadata": {"name": "p2", "namespace": "kube-system"}, "status": {"phase": "Pending"}},
        ]})
        result = get_k8s("http://k8s:6443", "token")
        assert result["pods"] == 2
        assert result["running"] == 1
        assert result["namespaces"] == 2


class TestGitea:
    @patch("server.integrations.simple_infra._git_devops_client")
    def test_uses_x_total_count_header(self, mock_client):
        from server.integrations.simple import get_gitea
        resp = _mock_response(json_data={"data": []}, headers={"x-total-count": "42"})
        mock_client.get.return_value = resp
        result = get_gitea("http://gitea:3000", "token")
        assert result["repos"] == 42

    @patch("server.integrations.simple_infra._git_devops_client")
    def test_falls_back_to_body(self, mock_client):
        from server.integrations.simple import get_gitea
        resp = _mock_response(json_data={"data": [{"id": 1}, {"id": 2}]}, headers={})
        mock_client.get.return_value = resp
        result = get_gitea("http://gitea:3000", "token")
        assert result["repos"] == 2


class TestGitlab:
    @patch("server.integrations.simple_infra._git_devops_client")
    def test_uses_x_total_header(self, mock_client):
        from server.integrations.simple import get_gitlab
        resp = _mock_response(json_data=[], headers={"x-total": "55"})
        mock_client.get.return_value = resp
        result = get_gitlab("http://gitlab:443", "token")
        assert result["projects"] == 55


class TestGithub:
    @patch("server.integrations.simple_infra._git_devops_client")
    def test_returns_repo_count(self, mock_client):
        from server.integrations.simple import get_github
        resp = _mock_response(json_data=[{"id": 1}, {"id": 2}])
        mock_client.get.return_value = resp
        result = get_github("ghp_xxx")
        assert result["repos"] == 2


class TestPaperless:
    @patch("server.integrations.simple_infra._http_get")
    def test_returns_document_count(self, mock_get):
        from server.integrations.simple import get_paperless
        mock_get.return_value = {"count": 1234}
        result = get_paperless("http://paperless:8000", "token")
        assert result["documents"] == 1234


class TestVaultwarden:
    @patch("server.integrations.simple_infra._security_client")
    def test_returns_online(self, mock_client):
        from server.integrations.simple import get_vaultwarden
        mock_client.get.return_value = _mock_response()
        result = get_vaultwarden("http://vw:80", "admin-token")
        assert result["status"] == "online"


class TestWeather:
    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_weather_data(self, mock_get):
        from server.integrations.simple import get_weather
        mock_get.return_value = {
            "weather": [{"description": "clear sky", "icon": "01d"}],
            "main": {"temp": 22.5, "feels_like": 21.3, "humidity": 55},
            "name": "London",
        }
        result = get_weather("key", "London")
        assert result["temp"] == 22.5
        assert result["city"] == "London"


class TestScrutinyIntelligence:
    def test_returns_none_when_no_url(self):
        from server.integrations.simple import get_scrutiny_intelligence
        assert get_scrutiny_intelligence("") is None

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_predictions(self, mock_get):
        from server.integrations.simple import get_scrutiny_intelligence
        mock_get.side_effect = [
            # summary
            {"data": {"summary": {
                "wwn1": {
                    "device": {"device_name": "sda", "model_name": "WD",
                               "serial_number": "ABC", "device_status": 0},
                    "smart": {"power_on_hours": 10000, "temp": 35},
                },
            }}},
            # details for wwn1
            {"data": {"smart_results": []}},
        ]
        result = get_scrutiny_intelligence("http://scrutiny:8080")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["wwn"] == "wwn1"

    @patch("server.integrations.simple_monitoring._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.simple import get_scrutiny_intelligence
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_scrutiny_intelligence("http://scrutiny:8080")
        assert result["status"] == "offline"


# ===========================================================================
# 4. Cookie-based auth — UniFi Controller, qBittorrent
# ===========================================================================

class TestUnifiController:
    """UniFi uses a dedicated httpx.Client to isolate cookie jar."""

    def test_returns_none_when_no_url(self):
        from server.integrations.unifi import get_unifi
        assert get_unifi("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        from server.integrations.unifi import get_unifi
        assert get_unifi("http://unifi:8443", "", "pass") is None

    @patch("server.integrations.unifi.httpx.Client")
    def test_returns_data_on_success(self, mock_client_cls):
        from server.integrations.unifi import get_unifi
        mock_client = _mock_client_ctx(mock_client_cls)

        login_resp = _mock_response(json_data={"meta": {"rc": "ok"}})
        login_resp.cookies = {"unifises": "session123"}
        dev_resp = _mock_response(json_data={"data": [
            {"adopted": True, "name": "USW-24"},
            {"adopted": True, "name": "UAP-AC"},
            {"adopted": False, "name": "USG"},
        ]})
        sta_resp = _mock_response(json_data={"data": [
            {"mac": "aa:bb:cc:dd:ee:01"}, {"mac": "aa:bb:cc:dd:ee:02"},
        ]})
        logout_resp = _mock_response()

        mock_client.post.side_effect = [login_resp, logout_resp]
        mock_client.get.side_effect = [dev_resp, sta_resp]

        result = get_unifi("http://unifi:8443", "admin", "pass")
        assert result["status"] == "online"
        assert result["devices"] == 3
        assert result["adopted"] == 2
        assert result["clients"] == 2

    @patch("server.integrations.unifi.httpx.Client")
    def test_returns_none_on_login_failure(self, mock_client_cls):
        from server.integrations.unifi import get_unifi
        mock_client = _mock_client_ctx(mock_client_cls)
        login_resp = _mock_response(status_code=401)
        # raise_for_status is not called explicitly; status_code check is used
        login_resp.raise_for_status = MagicMock()
        login_resp.status_code = 401
        mock_client.post.return_value = login_resp
        result = get_unifi("http://unifi:8443", "admin", "wrongpass")
        assert result is None

    @patch("server.integrations.unifi.httpx.Client")
    def test_returns_none_on_http_error(self, mock_client_cls):
        from server.integrations.unifi import get_unifi
        mock_client = _mock_client_ctx(mock_client_cls)
        mock_client.post.side_effect = httpx.HTTPError("connection failed")
        result = get_unifi("http://unifi:8443", "admin", "pass")
        assert result is None

    @patch("server.integrations.unifi.httpx.Client")
    def test_uses_custom_site(self, mock_client_cls):
        from server.integrations.unifi import get_unifi
        mock_client = _mock_client_ctx(mock_client_cls)

        login_resp = _mock_response()
        login_resp.cookies = {"unifises": "session"}
        dev_resp = _mock_response(json_data={"data": []})
        sta_resp = _mock_response(json_data={"data": []})
        logout_resp = _mock_response()

        mock_client.post.side_effect = [login_resp, logout_resp]
        mock_client.get.side_effect = [dev_resp, sta_resp]

        get_unifi("http://unifi:8443", "admin", "pass", site="mysite")
        # Verify the site parameter was used in the API calls
        dev_call_url = mock_client.get.call_args_list[0][0][0]
        assert "/api/s/mysite/" in dev_call_url


class TestQbittorrent:
    """qBittorrent uses a dedicated httpx.Client for form login + cookies."""

    def test_returns_none_when_no_url(self):
        from server.integrations.qbittorrent import get_qbit
        assert get_qbit("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        from server.integrations.qbittorrent import get_qbit
        assert get_qbit("http://qbit:8080", "", "pass") is None

    @patch("server.integrations.qbittorrent.httpx.Client")
    def test_returns_data_on_success(self, mock_client_cls):
        from server.integrations.qbittorrent import get_qbit
        mock_client = _mock_client_ctx(mock_client_cls)

        login_resp = _mock_response()
        login_resp.headers = {"set-cookie": "SID=abc123"}
        data_resp = _mock_response(json_data={
            "server_state": {"dl_info_speed": 1_000_000, "up_info_speed": 500_000},
            "torrents": {
                "hash1": {"state": "downloading"},
                "hash2": {"state": "stalledDL"},
                "hash3": {"state": "uploading"},
                "hash4": {"state": "metaDL"},
            },
        })
        mock_client.post.return_value = login_resp
        mock_client.get.return_value = data_resp

        result = get_qbit("http://qbit:8080", "admin", "pass")
        assert result["status"] == "online"
        assert result["dl_speed"] == 1_000_000
        assert result["up_speed"] == 500_000
        assert result["active_torrents"] == 3  # downloading + stalledDL + metaDL

    @patch("server.integrations.qbittorrent.httpx.Client")
    def test_returns_offline_when_no_cookie(self, mock_client_cls):
        from server.integrations.qbittorrent import get_qbit
        mock_client = _mock_client_ctx(mock_client_cls)

        login_resp = _mock_response()
        login_resp.headers = {}  # No set-cookie
        mock_client.post.return_value = login_resp

        result = get_qbit("http://qbit:8080", "admin", "wrongpass")
        assert result["status"] == "offline"
        assert result["active_torrents"] == 0

    @patch("server.integrations.qbittorrent.httpx.Client")
    def test_returns_offline_on_error(self, mock_client_cls):
        from server.integrations.qbittorrent import get_qbit
        mock_client = _mock_client_ctx(mock_client_cls)
        mock_client.post.side_effect = httpx.HTTPError("fail")

        result = get_qbit("http://qbit:8080", "admin", "pass")
        assert result["status"] == "offline"


# ===========================================================================
# 5. Proxmox VE (PVEAPIToken auth)
# ===========================================================================

class TestProxmox:
    def test_returns_none_when_no_url(self):
        from server.integrations.proxmox import get_proxmox
        assert get_proxmox("", "root", "token", "value") is None

    def test_returns_none_when_no_user(self):
        from server.integrations.proxmox import get_proxmox
        assert get_proxmox("http://pve:8006", "", "token", "value") is None

    def test_returns_none_when_no_token_name(self):
        from server.integrations.proxmox import get_proxmox
        assert get_proxmox("http://pve:8006", "root", "", "value") is None

    def test_returns_none_when_no_token_value(self):
        from server.integrations.proxmox import get_proxmox
        assert get_proxmox("http://pve:8006", "root", "token", "") is None

    @patch("server.integrations.proxmox._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = [
            # nodes
            {"data": [
                {"node": "pve1", "status": "online", "cpu": 0.25, "mem": 4 * 1024**3, "maxmem": 16 * 1024**3},
            ]},
            # qemu VMs for pve1
            {"data": [
                {"vmid": 100, "name": "ubuntu-vm", "status": "running", "cpu": 0.1, "mem": 1 * 1024**3, "maxmem": 4 * 1024**3},
            ]},
            # lxc containers for pve1
            {"data": [
                {"vmid": 200, "name": "dns-ct", "status": "running", "cpu": 0.05, "mem": 512 * 1024**2, "maxmem": 2 * 1024**3},
            ]},
        ]
        result = get_proxmox("http://pve:8006", "root", "noba", "secret-token-value")
        assert result["status"] == "online"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["name"] == "pve1"
        assert result["nodes"][0]["cpu"] == 25.0
        assert len(result["vms"]) == 2
        assert result["vms"][0]["type"] == "qemu"
        assert result["vms"][1]["type"] == "lxc"

    @patch("server.integrations.proxmox._http_get")
    def test_appends_pam_to_user_without_realm(self, mock_get):
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = [
            {"data": [{"node": "pve1", "status": "online", "cpu": 0, "mem": 0, "maxmem": 1}]},
            {"data": []},
            {"data": []},
        ]
        get_proxmox("http://pve:8006", "root", "noba", "value")
        # Verify the auth header uses root@pam
        auth_header = mock_get.call_args_list[0][0][1]["Authorization"]
        assert "root@pam" in auth_header

    @patch("server.integrations.proxmox._http_get")
    def test_preserves_realm_in_user(self, mock_get):
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = [
            {"data": [{"node": "pve1", "status": "online", "cpu": 0, "mem": 0, "maxmem": 1}]},
            {"data": []},
            {"data": []},
        ]
        get_proxmox("http://pve:8006", "admin@pve", "noba", "value")
        auth_header = mock_get.call_args_list[0][0][1]["Authorization"]
        assert "admin@pve!" in auth_header
        assert "admin@pve@pam" not in auth_header

    @patch("server.integrations.proxmox._http_get")
    def test_returns_offline_on_error(self, mock_get):
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_proxmox("http://pve:8006", "root", "noba", "value")
        assert result["status"] == "offline"

    @patch("server.integrations.proxmox._http_get")
    def test_tolerates_vm_fetch_failure(self, mock_get):
        """Node-level data should still return even if VM fetch fails."""
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = [
            {"data": [{"node": "pve1", "status": "online", "cpu": 0.5, "mem": 8 * 1024**3, "maxmem": 16 * 1024**3}]},
            httpx.HTTPError("qemu fail"),
            httpx.HTTPError("lxc fail"),
        ]
        result = get_proxmox("http://pve:8006", "root", "noba", "value")
        assert result["status"] == "online"
        assert len(result["nodes"]) == 1
        assert len(result["vms"]) == 0


# ===========================================================================
# 6. Pi-hole (v6/v5 fallback, session caching)
# ===========================================================================

class TestPihole:
    def test_returns_none_when_no_url(self):
        from server.integrations.pihole import get_pihole
        assert get_pihole("", "") is None

    @patch("server.integrations.pihole._http_get")
    def test_v6_success_with_password(self, mock_get):
        from server.integrations.pihole import get_pihole, _pihole_sessions, _pihole_session_lock
        # Clear session cache
        with _pihole_session_lock:
            _pihole_sessions.clear()

        # Mock the v6 auth + stats
        with patch("server.integrations.pihole._client") as mock_client:
            auth_resp = _mock_response(json_data={
                "session": {"sid": "test-sid-123"},
            })
            mock_client.post.return_value = auth_resp

            # Pi-hole v6 schema: blocked + percent_blocked live under `queries`,
            # and status is derived from gravity.domains_being_blocked > 0.
            mock_get.return_value = {
                "queries": {"total": 50000, "blocked": 5000, "percent_blocked": 10.0},
                "gravity": {"domains_being_blocked": 100000},
            }

            result = get_pihole("http://pihole:80", "", password="mypassword")
            assert result["queries"] == 50000
            assert result["blocked"] == 5000
            assert result["percent"] == 10.0
            assert result["domains"] == "100,000"
            assert result["status"] == "enabled"

    @patch("server.integrations.pihole._http_get")
    def test_v6_with_token_as_sid(self, mock_get):
        from server.integrations.pihole import get_pihole
        mock_get.return_value = {
            "queries": {"total": 1000},
            "ads": {"blocked": 100, "percentage": 10.0},
            "gravity": {"status": "enabled", "domains_being_blocked": 50000},
        }
        result = get_pihole("http://pihole:80", "my-sid-token")
        assert result["queries"] == 1000

    @patch("server.integrations.pihole._http_get")
    def test_v5_fallback(self, mock_get):
        from server.integrations.pihole import get_pihole
        # v6 fails, v5 succeeds
        mock_get.side_effect = [
            httpx.HTTPError("v6 fail"),
            {"dns_queries_today": 30000, "ads_blocked_today": 3000,
             "ads_percentage_today": 10.0, "status": "enabled",
             "domains_being_blocked": 80000},
        ]
        result = get_pihole("http://pihole:80", "v5token")
        assert result["queries"] == 30000
        assert result["status"] == "enabled"

    @patch("server.integrations.pihole._http_get")
    def test_returns_none_when_both_fail(self, mock_get):
        from server.integrations.pihole import get_pihole
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_pihole("http://pihole:80", "token")
        assert result is None

    def test_auto_prepends_http(self):
        """URLs without scheme should get http:// prepended."""
        from server.integrations.pihole import get_pihole
        with patch("server.integrations.pihole._http_get") as mock_get:
            mock_get.return_value = {
                "queries": {"total": 1}, "ads": {"blocked": 0, "percentage": 0},
                "gravity": {"status": "ok", "domains_being_blocked": 0},
            }
            get_pihole("pihole.local", "sid")
            url_called = mock_get.call_args[0][0]
            assert url_called.startswith("http://")

    def test_strips_admin_path(self):
        from server.integrations.pihole import get_pihole
        with patch("server.integrations.pihole._http_get") as mock_get:
            mock_get.return_value = {
                "queries": {"total": 1}, "ads": {"blocked": 0, "percentage": 0},
                "gravity": {"status": "ok", "domains_being_blocked": 0},
            }
            get_pihole("http://pihole/admin", "sid")
            url_called = mock_get.call_args[0][0]
            assert "/admin/admin" not in url_called


# ===========================================================================
# 7. Home Assistant (Bearer token, 3 functions)
# ===========================================================================

class TestHass:
    def test_returns_none_when_no_url(self):
        from server.integrations.hass import get_hass
        assert get_hass("", "token") is None

    def test_returns_none_when_no_token(self):
        from server.integrations.hass import get_hass
        assert get_hass("http://hass:8123", "") is None

    @patch("server.integrations.hass._http_get")
    def test_returns_data_on_success(self, mock_get):
        from server.integrations.hass import get_hass
        mock_get.return_value = [
            {"entity_id": "light.kitchen", "state": "on"},
            {"entity_id": "light.bedroom", "state": "off"},
            {"entity_id": "switch.fan", "state": "on"},
            {"entity_id": "automation.sunset", "state": "on"},
            {"entity_id": "sensor.temp", "state": "22.5"},
        ]
        result = get_hass("http://hass:8123", "token")
        assert result["status"] == "online"
        assert result["entities"] == 5
        assert result["lights_on"] == 1
        assert result["switches_on"] == 1
        assert result["automations"] == 1
        assert result["domains"]["light"] == 2
        assert result["domains"]["sensor"] == 1

    @patch("server.integrations.hass._http_get")
    def test_returns_none_on_non_list_response(self, mock_get):
        from server.integrations.hass import get_hass
        mock_get.return_value = {"error": "unauthorized"}
        assert get_hass("http://hass:8123", "token") is None

    @patch("server.integrations.hass._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.hass import get_hass
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_hass("http://hass:8123", "token") is None


class TestHassEntities:
    def test_returns_none_when_no_url(self):
        from server.integrations.hass import get_hass_entities
        assert get_hass_entities("", "token") is None

    @patch("server.integrations.hass._http_get")
    def test_returns_filtered_entities(self, mock_get):
        from server.integrations.hass import get_hass_entities
        mock_get.return_value = [
            {"entity_id": "light.kitchen", "state": "on",
             "attributes": {"friendly_name": "Kitchen Light", "brightness": 255}},
            {"entity_id": "sensor.temp", "state": "22.5",
             "attributes": {"friendly_name": "Temperature", "unit_of_measurement": "C",
                            "device_class": "temperature"}},
        ]
        result = get_hass_entities("http://hass:8123", "token", entity_filter="light")
        assert result is not None
        assert len(result["entities"]) == 1
        assert result["entities"][0]["entity_id"] == "light.kitchen"
        assert result["entities"][0]["brightness"] == 255
        assert result["total"] == 2

    @patch("server.integrations.hass._http_get")
    def test_returns_all_entities_without_filter(self, mock_get):
        from server.integrations.hass import get_hass_entities
        mock_get.return_value = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen"}},
            {"entity_id": "sensor.temp", "state": "22", "attributes": {"friendly_name": "Temp"}},
        ]
        result = get_hass_entities("http://hass:8123", "token")
        assert len(result["entities"]) == 2

    @patch("server.integrations.hass._http_get")
    def test_domain_specific_attributes(self, mock_get):
        from server.integrations.hass import get_hass_entities
        mock_get.return_value = [
            {"entity_id": "climate.hvac", "state": "heating",
             "attributes": {"friendly_name": "HVAC", "temperature": 22,
                            "current_temperature": 20, "hvac_action": "heating"}},
            {"entity_id": "media_player.tv", "state": "playing",
             "attributes": {"friendly_name": "TV", "media_title": "Movie",
                            "source": "HDMI1"}},
            {"entity_id": "cover.garage", "state": "open",
             "attributes": {"friendly_name": "Garage Door", "current_position": 100}},
        ]
        result = get_hass_entities("http://hass:8123", "token")
        entities = {e["entity_id"]: e for e in result["entities"]}
        assert entities["climate.hvac"]["hvac_action"] == "heating"
        assert entities["media_player.tv"]["media_title"] == "Movie"
        assert entities["cover.garage"]["current_position"] == 100

    @patch("server.integrations.hass._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.hass import get_hass_entities
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_hass_entities("http://hass:8123", "token") is None


class TestHassServices:
    def test_returns_none_when_no_url(self):
        from server.integrations.hass import get_hass_services
        assert get_hass_services("", "token") is None

    def test_returns_none_when_no_token(self):
        from server.integrations.hass import get_hass_services
        assert get_hass_services("http://hass:8123", "") is None

    @patch("server.integrations.hass._http_get")
    def test_returns_services(self, mock_get):
        from server.integrations.hass import get_hass_services
        mock_get.return_value = [
            {"domain": "light", "services": {
                "turn_on": {"name": "Turn on", "description": "Turn on a light"},
                "turn_off": {"name": "Turn off", "description": "Turn off a light"},
            }},
            {"domain": "switch", "services": {
                "toggle": {"name": "Toggle", "description": "Toggle a switch"},
            }},
        ]
        result = get_hass_services("http://hass:8123", "token")
        assert isinstance(result, list)
        assert len(result) == 3
        domains = [s["domain"] for s in result]
        assert "light" in domains
        assert "switch" in domains

    @patch("server.integrations.hass._http_get")
    def test_returns_none_on_error(self, mock_get):
        from server.integrations.hass import get_hass_services
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_hass_services("http://hass:8123", "token") is None


# ===========================================================================
# 8. TrueNAS WebSocket driver (JSON-RPC 2.0)
# ===========================================================================

class TestTruenasWsHelpers:
    def test_get_ws_url_https(self):
        from server.integrations.truenas_ws import _get_ws_url
        assert _get_ws_url("https://truenas.local") == "wss://truenas.local/api/current"

    def test_get_ws_url_http(self):
        from server.integrations.truenas_ws import _get_ws_url
        assert _get_ws_url("http://truenas.local") == "ws://truenas.local/api/current"

    def test_get_ws_url_strips_trailing_slash(self):
        from server.integrations.truenas_ws import _get_ws_url
        assert _get_ws_url("https://truenas.local/") == "wss://truenas.local/api/current"


class TestTruenasWsJsonrpc:
    def test_jsonrpc_call_success(self):
        from server.integrations.truenas_ws import _jsonrpc_call
        mock_ws = MagicMock()
        response = {"jsonrpc": "2.0", "id": 1, "result": [{"name": "app1"}]}
        mock_ws.recv.return_value = json.dumps(response)

        # Patch time to control msg_id
        with patch("server.integrations.truenas_ws.time") as mock_time:
            mock_time.time.return_value = 0.001  # msg_id = 1
            result = _jsonrpc_call(mock_ws, "app.query")

        assert result == [{"name": "app1"}]

    def test_jsonrpc_call_error(self):
        from server.integrations.truenas_ws import _jsonrpc_call
        mock_ws = MagicMock()
        response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "not found"}}
        mock_ws.recv.return_value = json.dumps(response)

        with patch("server.integrations.truenas_ws.time") as mock_time:
            mock_time.time.return_value = 0.001
            with pytest.raises(RuntimeError, match="JSON-RPC error"):
                _jsonrpc_call(mock_ws, "bad.method")

    def test_jsonrpc_call_timeout(self):
        from server.integrations.truenas_ws import _jsonrpc_call
        mock_ws = MagicMock()
        mock_ws.recv.side_effect = Exception("no data")

        with patch("server.integrations.truenas_ws.time") as mock_time:
            # First call for msg_id, then simulate deadline passed
            mock_time.time.side_effect = [0.001, 100.0, 200.0]
            with pytest.raises(TimeoutError, match="JSON-RPC timeout"):
                _jsonrpc_call(mock_ws, "slow.method", timeout=1)


class TestTruenasWsDriver:
    def test_returns_none_when_no_url(self):
        from server.integrations.truenas_ws import get_truenas
        assert get_truenas("", "key") is None

    def test_returns_none_when_no_key(self):
        from server.integrations.truenas_ws import get_truenas
        assert get_truenas("https://truenas:443", "") is None

    def test_returns_data_on_success(self):
        from server.integrations.truenas_ws import get_truenas
        from contextlib import contextmanager

        @contextmanager
        def _fake_connect(url, key):
            yield MagicMock()

        with patch("server.integrations.truenas_ws._connect", _fake_connect), \
             patch("server.integrations.truenas_ws._get_truenas_rest", return_value={"status": "rest_fallback"}), \
             patch("server.integrations.truenas_ws._jsonrpc_call") as mock_rpc:
            mock_rpc.side_effect = [
                [{"name": "plex", "state": "RUNNING"}],         # app.query
                [{"level": "WARNING", "formatted": "Disk hot", "dismissed": False}],  # alert.list
                [{"id": 1, "name": "testvm", "status": {"state": "RUNNING"}}],  # vm.query
                [{"name": "tank", "status": "ONLINE", "healthy": True}],  # pool.query
            ]

            result = get_truenas("https://truenas:443", "apikey")

        # If WS path works, status is "online"; if REST fallback was hit, it's "rest_fallback"
        assert result is not None
        assert result["status"] == "online", f"Got REST fallback instead of WS path: {result}"
        assert len(result["apps"]) == 1
        assert result["apps"][0]["name"] == "plex"
        assert len(result["alerts"]) == 1
        assert len(result["vms"]) == 1
        assert len(result["pools"]) == 1
        assert result["pools"][0]["healthy"] is True

    def test_dismissed_alerts_excluded(self):
        from server.integrations.truenas_ws import get_truenas
        from contextlib import contextmanager

        @contextmanager
        def _fake_connect(url, key):
            yield MagicMock()

        with patch("server.integrations.truenas_ws._connect", _fake_connect), \
             patch("server.integrations.truenas_ws._get_truenas_rest", return_value={"status": "rest_fallback", "alerts": []}), \
             patch("server.integrations.truenas_ws._jsonrpc_call") as mock_rpc:
            mock_rpc.side_effect = [
                [],
                [{"level": "WARNING", "formatted": "Old", "dismissed": True}],
                [],
                [],
            ]
            result = get_truenas("https://truenas:443", "apikey")

        assert result["alerts"] == []

    @patch("server.integrations.truenas_ws._get_truenas_rest")
    def test_falls_back_to_rest_on_ws_error(self, mock_rest):
        from server.integrations.truenas_ws import get_truenas
        mock_rest.return_value = {"apps": [], "alerts": [], "vms": [], "status": "online"}

        with patch("server.integrations.truenas_ws._connect") as mock_connect:
            mock_connect.side_effect = Exception("WebSocket connection failed")
            result = get_truenas("https://truenas:443", "apikey")

        assert result["status"] == "online"
        mock_rest.assert_called_once()

    def test_falls_back_to_rest_when_websocket_not_installed(self):
        from server.integrations.truenas_ws import get_truenas
        with patch("server.integrations.truenas_ws._get_truenas_rest") as mock_rest:
            mock_rest.return_value = {"apps": [], "alerts": [], "vms": [], "status": "online"}
            with patch.dict("sys.modules", {"websocket": None}):
                # Force ImportError by making the import fail
                import builtins
                real_import = builtins.__import__

                def mock_import(name, *args, **kwargs):
                    if name == "websocket":
                        raise ImportError("no websocket")
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=mock_import):
                    result = get_truenas("https://truenas:443", "apikey")

            assert result["status"] == "online"

    def test_tolerates_individual_rpc_failures(self):
        """If one RPC call fails, others should still succeed."""
        from server.integrations.truenas_ws import get_truenas
        from contextlib import contextmanager

        @contextmanager
        def _fake_connect(url, key):
            yield MagicMock()

        with patch("server.integrations.truenas_ws._connect", _fake_connect), \
             patch("server.integrations.truenas_ws._get_truenas_rest", return_value={"status": "rest_fallback"}), \
             patch("server.integrations.truenas_ws._jsonrpc_call") as mock_rpc:
            mock_rpc.side_effect = [
                [{"name": "app1", "state": "RUNNING"}],  # app.query succeeds
                RuntimeError("alert.list failed"),         # alert.list fails
                [],                                        # vm.query succeeds
                RuntimeError("pool.query failed"),         # pool.query fails
            ]
            result = get_truenas("https://truenas:443", "apikey")

        assert result["status"] == "online"
        assert len(result["apps"]) == 1
        assert result["alerts"] == []
        assert result["vms"] == []


class TestTruenasWsRest:
    """Tests for the REST fallback function in truenas_ws module."""

    @patch("server.integrations.base._http_get")
    def test_rest_fallback_success(self, mock_get):
        from server.integrations.truenas_ws import _get_truenas_rest
        mock_get.side_effect = [
            [{"name": "app1", "state": "RUNNING"}],
            [],
            [{"id": 1, "name": "vm1", "status": {"state": "RUNNING"}}],
        ]
        result = _get_truenas_rest("http://truenas:443", "apikey")
        assert result["status"] == "online"
        assert len(result["apps"]) == 1

    @patch("server.integrations.base._http_get")
    def test_rest_fallback_failure(self, mock_get):
        from server.integrations.truenas_ws import _get_truenas_rest
        mock_get.side_effect = httpx.HTTPError("fail")
        result = _get_truenas_rest("http://truenas:443", "apikey")
        assert result["status"] == "offline"


class TestTruenasWsCleanup:
    def test_cleanup_stale_connections(self):
        from server.integrations.truenas_ws import (
            cleanup_stale_connections, _ws_cache, _cache_lock, _CACHE_EXPIRY,
        )
        mock_ws = MagicMock()
        with _cache_lock:
            _ws_cache["http://old"] = {"ws": mock_ws, "last_used": time.time() - _CACHE_EXPIRY - 10}
            _ws_cache["http://fresh"] = {"ws": MagicMock(), "last_used": time.time()}

        cleanup_stale_connections()

        with _cache_lock:
            assert "http://old" not in _ws_cache
            assert "http://fresh" in _ws_cache
            # Clean up
            del _ws_cache["http://fresh"]

        mock_ws.close.assert_called_once()


# ===========================================================================
# 9. Edge cases — timeouts, invalid configs, malformed responses
# ===========================================================================

class TestEdgeCases:
    """Cross-cutting edge cases for integration drivers."""

    @patch("server.integrations.simple_media._http_get")
    def test_plex_malformed_response(self, mock_get):
        """Missing MediaContainer key should not crash."""
        from server.integrations.simple import get_plex
        mock_get.return_value = {}
        result = get_plex("http://plex:32400", "token")
        assert result["sessions"] == 0

    @patch("server.integrations.simple_monitoring._http_get")
    def test_speedtest_malformed_data(self, mock_get):
        """Malformed data block should not crash."""
        from server.integrations.simple import get_speedtest
        mock_get.return_value = {"data": {"download": None, "upload": None, "ping": None}}
        # TypeError from None arithmetic => returns error dict
        result = get_speedtest("http://st:8080")
        assert result["status"] == "offline"

    @patch("server.integrations.simple_media._http_get")
    def test_jellyfin_null_sessions(self, mock_get):
        """None sessions list should not crash."""
        from server.integrations.simple import get_jellyfin
        mock_get.side_effect = [
            None,  # sessions = None
            {"MovieCount": 5},
        ]
        result = get_jellyfin("http://jf:8096", "key")
        assert result["streams"] == 0

    @patch("server.integrations.simple_monitoring._http_get")
    def test_kuma_no_monitor_lines(self, mock_get):
        """Metrics endpoint with no monitor_status lines."""
        from server.integrations.simple import get_kuma
        with patch("server.integrations.simple_monitoring._client") as mock_client:
            resp = MagicMock()
            resp.text = "# HELP uptime\n# TYPE uptime gauge\nuptime 12345\n"
            resp.raise_for_status.return_value = None
            mock_client.get.return_value = resp
            result = get_kuma("http://kuma:3001")
            assert result == []

    @patch("server.integrations.simple_network._http_get")
    def test_adguard_zero_queries(self, mock_get):
        """Zero queries should not cause ZeroDivisionError."""
        from server.integrations.simple import get_adguard
        mock_get.return_value = {"num_dns_queries": 0, "num_blocked_filtering": 0}
        result = get_adguard("http://adguard:3000", "", "")
        assert result["percent"] == 0

    @patch("server.integrations.simple_network._http_get")
    def test_cloudflare_zero_bandwidth(self, mock_get):
        """Zero bandwidth should not cause ZeroDivisionError."""
        from server.integrations.simple import get_cloudflare
        mock_get.return_value = {
            "result": {"totals": {
                "requests": {"all": 0},
                "threats": {"all": 0},
                "bandwidth": {"all": 0, "cached": 0},
            }},
        }
        result = get_cloudflare("token", "zone")
        assert result["cache_hit_ratio"] == 0.0

    def test_trailing_slash_stripping(self):
        """All drivers should handle trailing slashes gracefully."""
        from server.integrations.simple import get_plex
        with patch("server.integrations.simple_media._http_get") as mock_get:
            mock_get.side_effect = [
                {"MediaContainer": {"size": 0}},
                {"MediaContainer": {"size": 0}},
            ]
            get_plex("http://plex:32400/", "token")
            url_called = mock_get.call_args_list[0][0][0]
            assert "//" not in url_called.replace("http://", "")

    @patch("server.integrations.proxmox._http_get")
    def test_proxmox_zero_maxmem_no_division_error(self, mock_get):
        """maxmem=0 should not cause ZeroDivisionError due to `or 1` guard."""
        from server.integrations.proxmox import get_proxmox
        mock_get.side_effect = [
            {"data": [{"node": "pve1", "status": "online", "cpu": 0, "mem": 0, "maxmem": 0}]},
            {"data": [{"vmid": 100, "name": "vm1", "status": "running",
                        "cpu": 0, "mem": 0, "maxmem": 0}]},
            {"data": []},
        ]
        result = get_proxmox("http://pve:8006", "root", "noba", "value")
        assert result["status"] == "online"
        # Should not crash; mem_percent should be 0 due to `or 1` guard
        assert result["nodes"][0]["mem_percent"] == 0.0

    @patch("server.integrations.simple_monitoring._http_get")
    def test_hass_entities_capped_at_500(self, mock_get):
        """Entity list should be capped at 500."""
        from server.integrations.hass import get_hass_entities
        with patch("server.integrations.hass._http_get") as hass_mock:
            entities = [
                {"entity_id": f"sensor.s{i}", "state": str(i), "attributes": {"friendly_name": f"S{i}"}}
                for i in range(600)
            ]
            hass_mock.return_value = entities
            result = get_hass_entities("http://hass:8123", "token")
            assert len(result["entities"]) == 500
            assert result["total"] == 600

    def test_base_http_get_raises_on_non_200(self):
        """_http_get should raise on non-200 responses."""
        from server.integrations.base import _http_get
        with patch("server.integrations.base._client") as mock_client:
            resp = _mock_response(status_code=500)
            mock_client.get.return_value = resp
            from server.integrations.base import TransientError
            with pytest.raises(TransientError):
                _http_get("http://example.com/api")
