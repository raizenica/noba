"""Tests for server.integrations – all 24 new integration functions."""
from __future__ import annotations

import httpx
from unittest.mock import MagicMock, patch

from server.integrations import (
    get_authentik,
    get_cloudflare,
    get_esphome,
    get_gitea,
    get_github,
    get_gitlab,
    get_homebridge,
    get_k8s,
    get_nextcloud,
    get_npm,
    get_omv,
    get_overseerr,
    get_paperless,
    get_pikvm,
    get_prowlarr,
    get_servarr_calendar,
    get_servarr_extended,
    get_tautulli,
    get_traefik,
    get_unifi_protect,
    get_vaultwarden,
    get_weather,
    get_xcpng,
    get_z2m,
)


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
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


# ===========================================================================
# 1. Tautulli
# ===========================================================================

class TestTautulli:
    def test_returns_none_when_no_url(self):
        assert get_tautulli("", "key") is None

    def test_returns_none_when_no_key(self):
        assert get_tautulli("http://tautulli:8181", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.side_effect = [
            # get_activity response
            {
                "response": {
                    "data": {
                        "stream_count": 2,
                        "stream_count_direct_play": 1,
                        "stream_count_transcode": 1,
                    },
                },
            },
            # get_home_stats response (stat group format)
            {
                "response": {
                    "data": [
                        {
                            "rows": [
                                {"friendly_name": "Alice", "total_plays": 100},
                                {"friendly_name": "Bob", "total_plays": 50},
                            ],
                        },
                    ],
                },
            },
        ]
        result = get_tautulli("http://tautulli:8181", "apikey")
        assert result is not None
        assert result["status"] == "online"
        assert result["streams"] == 2
        assert result["stream_count_direct_play"] == 1
        assert result["stream_count_transcode"] == 1
        assert len(result["top_users"]) == 2
        assert result["top_users"][0]["user"] == "Alice"

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        result = get_tautulli("http://tautulli:8181", "apikey")
        assert result is None


# ===========================================================================
# 2. Overseerr
# ===========================================================================

class TestOverseerr:
    def test_returns_none_when_no_url(self):
        assert get_overseerr("", "key") is None

    def test_returns_none_when_no_key(self):
        assert get_overseerr("http://overseerr:5055", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {
            "pending": 3, "approved": 10, "available": 8, "total": 21,
        }
        result = get_overseerr("http://overseerr:5055", "apikey")
        assert result is not None
        assert result["status"] == "online"
        assert result["pending"] == 3
        assert result["approved"] == 10
        assert result["available"] == 8
        assert result["total"] == 21

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_overseerr("http://overseerr:5055", "apikey") is None


# ===========================================================================
# 3. Prowlarr
# ===========================================================================

class TestProwlarr:
    def test_returns_none_when_no_url(self):
        assert get_prowlarr("", "key") is None

    def test_returns_none_when_no_key(self):
        assert get_prowlarr("http://prowlarr:9696", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "name": "NZBgeek"},
            {"id": 2, "name": "Torznab"},
        ]
        result = get_prowlarr("http://prowlarr:9696", "apikey")
        assert result is not None
        assert result["status"] == "online"
        assert result["indexer_count"] == 2

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_prowlarr("http://prowlarr:9696", "apikey") is None


# ===========================================================================
# 4. Servarr Extended
# ===========================================================================

class TestServarrExtended:
    def test_returns_none_when_no_url(self):
        assert get_servarr_extended("", "key") is None

    def test_returns_none_when_no_key(self):
        assert get_servarr_extended("http://radarr:7878", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.side_effect = [
            {"totalRecords": 5},                         # queue
            {"totalRecords": 12},                        # wanted/missing
            [                                            # rootfolder
                {"totalSpace": 2 * 1024**3, "freeSpace": 1 * 1024**3},
                {"totalSpace": 4 * 1024**3, "freeSpace": 2 * 1024**3},
            ],
        ]
        result = get_servarr_extended("http://radarr:7878", "key", "radarr")
        assert result is not None
        assert result["status"] == "online"
        assert result["queue_count"] == 5
        assert result["missing"] == 12
        assert result["total_space_gb"] == 6.0
        assert result["free_space_gb"] == 3.0
        assert result["service"] == "radarr"

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_servarr_extended("http://radarr:7878", "key") is None


# ===========================================================================
# 5. Servarr Calendar
# ===========================================================================

class TestServarrCalendar:
    def test_returns_none_when_no_url(self):
        assert get_servarr_calendar("", "key") is None

    def test_returns_none_when_no_key(self):
        assert get_servarr_calendar("http://sonarr:8989", "") is None

    @patch("server.integrations._http_get")
    def test_returns_episodes_on_success(self, mock_get):
        mock_get.return_value = [
            {
                "title": "S02E05",
                "series": {"title": "Breaking Bad"},
                "airDateUtc": "2026-03-20T00:00:00Z",
            },
            {
                "title": "The Matrix 5",
                "inCinemas": "2026-03-22",
            },
        ]
        result = get_servarr_calendar("http://sonarr:8989", "key")
        assert result is not None
        assert len(result) == 2
        assert result[0]["title"] == "Breaking Bad"
        assert result[0]["type"] == "episode"
        assert result[1]["title"] == "The Matrix 5"
        assert result[1]["type"] == "movie"

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_servarr_calendar("http://sonarr:8989", "key") is None


# ===========================================================================
# 6. Nextcloud
# ===========================================================================

class TestNextcloud:
    def test_returns_none_when_no_url(self):
        assert get_nextcloud("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        assert get_nextcloud("http://nc:443", "", "pass") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {
            "ocs": {
                "data": {
                    "nextcloud": {
                        "storage": {"num_files": 42000},
                        "system": {
                            "version": "28.0.1",
                            "freespace": 50 * 1024**3,
                            "freespacealiased": 100 * 1024**3,
                        },
                    },
                    "activeUsers": {"last5minutes": 3},
                },
            },
        }
        result = get_nextcloud("http://nc:443", "admin", "pass")
        assert result is not None
        assert result["status"] == "online"
        assert result["active_users"] == 3
        assert result["num_files"] == 42000
        assert result["version"] == "28.0.1"
        assert result["storage_free_gb"] == 50.0

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_nextcloud("http://nc:443", "admin", "pass") is None


# ===========================================================================
# 7. Traefik
# ===========================================================================

class TestTraefik:
    def test_returns_none_when_no_url(self):
        assert get_traefik("") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.side_effect = [
            # routers
            [{"name": "web@docker"}, {"name": "api@internal"}],
            # services
            [
                {"name": "svc1", "status": "enabled", "serverStatus": {}},
                {"name": "svc2", "status": "error", "serverStatus": {"http://back:80": "DOWN"}},
            ],
        ]
        result = get_traefik("http://traefik:8080")
        assert result is not None
        assert result["status"] == "online"
        assert result["routers"] == 2
        assert result["services"] == 2
        assert result["errors"] >= 1

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_traefik("http://traefik:8080") is None


# ===========================================================================
# 8. Nginx Proxy Manager
# ===========================================================================

class TestNpm:
    def test_returns_none_when_no_url(self):
        assert get_npm("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_npm("http://npm:81", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = [
            {"id": 1, "domain_names": ["app.example.com"]},
            {"id": 2, "domain_names": ["api.example.com"]},
            {"id": 3, "domain_names": ["dashboard.example.com"]},
        ]
        result = get_npm("http://npm:81", "jwt-token")
        assert result is not None
        assert result["status"] == "online"
        assert result["proxy_hosts"] == 3

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_npm("http://npm:81", "token") is None


# ===========================================================================
# 9. Authentik
# ===========================================================================

class TestAuthentik:
    def test_returns_none_when_no_url(self):
        assert get_authentik("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_authentik("http://authentik:9000", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.side_effect = [
            # users
            {"pagination": {"count": 25}},
            # events (failed logins)
            {"pagination": {"count": 4}},
        ]
        result = get_authentik("http://authentik:9000", "api-token")
        assert result is not None
        assert result["status"] == "online"
        assert result["users"] == 25
        assert result["failed_logins"] == 4

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_authentik("http://authentik:9000", "token") is None


# ===========================================================================
# 10. Cloudflare
# ===========================================================================

class TestCloudflare:
    def test_returns_none_when_no_token(self):
        assert get_cloudflare("", "zone123") is None

    def test_returns_none_when_no_zone(self):
        assert get_cloudflare("cf-token", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {
            "result": {
                "totals": {
                    "requests": {"all": 10000},
                    "threats": {"all": 42},
                    "bandwidth": {"all": 5 * 1024**3, "cached": 3 * 1024**3},
                },
            },
        }
        result = get_cloudflare("cf-token", "zone123")
        assert result is not None
        assert result["status"] == "online"
        assert result["requests"] == 10000
        assert result["threats"] == 42
        assert result["bandwidth_gb"] == round(5 * 1024**3 / 1024**3, 2)
        assert result["cache_hit_ratio"] == 60.0

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_cloudflare("cf-token", "zone123") is None


# ===========================================================================
# 11. OpenMediaVault (uses httpx.Client context manager)
# ===========================================================================

class TestOmv:
    def test_returns_none_when_no_url(self):
        assert get_omv("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        assert get_omv("http://omv:80", "", "pass") is None

    @patch("server.integrations.httpx.Client")
    def test_returns_data_on_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        login_resp = _mock_response(json_data={"response": "authenticated"})
        fs_resp = _mock_response(json_data=[
            {"devicefile": "/dev/sda1", "label": "data", "percentage": 45.3},
            {"devicefile": "/dev/sdb1", "label": "backup", "percentage": 72.1},
        ])
        mock_client.post.side_effect = [login_resp, fs_resp]

        result = get_omv("http://omv:80", "admin", "pass")
        assert result is not None
        assert result["status"] == "online"
        assert len(result["filesystems"]) == 2
        assert result["filesystems"][0]["label"] == "data"
        assert result["filesystems"][0]["percent"] == 45.3

    @patch("server.integrations.httpx.Client")
    def test_returns_none_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPError("fail")
        assert get_omv("http://omv:80", "admin", "pass") is None


# ===========================================================================
# 12. XCP-ng (uses shared _client.post)
# ===========================================================================

class TestXcpng:
    def test_returns_none_when_no_url(self):
        assert get_xcpng("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        assert get_xcpng("http://xcp:443", "", "pass") is None

    @patch("server.integrations._client")
    def test_returns_data_on_success(self, mock_client):
        login_resp = _mock_response(json_data={"result": "session-id-123"})
        vm_resp = _mock_response(json_data={
            "result": {
                "vm-ref-1": {
                    "name_label": "vm1",
                    "power_state": "Running",
                    "is_control_domain": False,
                    "is_a_template": False,
                },
                "vm-ref-2": {
                    "name_label": "vm2",
                    "power_state": "Halted",
                    "is_control_domain": False,
                    "is_a_template": False,
                },
                "vm-ref-dom0": {
                    "name_label": "Control domain",
                    "power_state": "Running",
                    "is_control_domain": True,
                    "is_a_template": False,
                },
            },
        })
        mock_client.post.side_effect = [login_resp, vm_resp]

        result = get_xcpng("http://xcp:443", "root", "pass")
        assert result is not None
        assert result["status"] == "online"
        assert result["vms"] == 2          # excludes control domain
        assert result["running_vms"] == 1  # only vm1 is Running

    @patch("server.integrations._client")
    def test_returns_none_on_error(self, mock_client):
        mock_client.post.side_effect = httpx.HTTPError("fail")
        assert get_xcpng("http://xcp:443", "root", "pass") is None


# ===========================================================================
# 13. Homebridge (uses httpx.Client context manager)
# ===========================================================================

class TestHomebridge:
    def test_returns_none_when_no_url(self):
        assert get_homebridge("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        assert get_homebridge("http://hb:8581", "", "pass") is None

    @patch("server.integrations.httpx.Client")
    def test_returns_data_on_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        login_resp = _mock_response(json_data={"access_token": "jwt123"})
        acc_resp = _mock_response(json_data=[
            {
                "serviceName": "Motion Sensor",
                "serviceCharacteristics": [
                    {"type": "BatteryLevel", "value": 15},
                ],
            },
            {
                "serviceName": "Light Bulb",
                "serviceCharacteristics": [
                    {"type": "On", "value": True},
                ],
            },
        ])
        mock_client.post.return_value = login_resp
        mock_client.get.return_value = acc_resp

        result = get_homebridge("http://hb:8581", "admin", "pass")
        assert result is not None
        assert result["status"] == "online"
        assert result["accessories"] == 2
        assert len(result["battery_devices"]) == 1
        assert result["battery_devices"][0]["name"] == "Motion Sensor"
        assert result["battery_devices"][0]["battery"] == 15

    @patch("server.integrations.httpx.Client")
    def test_returns_none_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPError("fail")
        assert get_homebridge("http://hb:8581", "admin", "pass") is None


# ===========================================================================
# 14. Zigbee2MQTT
# ===========================================================================

class TestZ2m:
    def test_returns_none_when_no_url(self):
        assert get_z2m("") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = [
            {
                "friendly_name": "Bedroom Light",
                "availability": {"state": "online"},
                "battery": 85,
                "interview_completed": True,
            },
            {
                "friendly_name": "Door Sensor",
                "availability": {"state": "offline"},
                "battery": 10,
                "interview_completed": True,
            },
            {
                "friendly_name": "Coordinator",
                "availability": {"state": "online"},
                "interview_completed": True,
            },
        ]
        result = get_z2m("http://z2m:8080")
        assert result is not None
        assert result["status"] == "online"
        assert result["devices"] == 3
        assert result["offline"] == 1
        assert len(result["low_battery"]) == 1
        assert result["low_battery"][0]["name"] == "Door Sensor"
        assert result["low_battery"][0]["battery"] == 10

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_z2m("http://z2m:8080") is None


# ===========================================================================
# 15. ESPHome
# ===========================================================================

class TestEsphome:
    def test_returns_none_when_no_url(self):
        assert get_esphome("") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = [
            {"name": "esp-kitchen", "status": "ONLINE", "connected": True},
            {"name": "esp-garage", "status": "OFFLINE", "connected": False},
            {"name": "esp-bedroom", "status": "ONLINE", "connected": True},
        ]
        result = get_esphome("http://esphome:6052")
        assert result is not None
        assert result["status"] == "online"
        assert result["nodes"] == 3
        assert result["online"] == 2

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_esphome("http://esphome:6052") is None


# ===========================================================================
# 16. UniFi Protect (uses httpx.Client context manager)
# ===========================================================================

class TestUnifiProtect:
    def test_returns_none_when_no_url(self):
        assert get_unifi_protect("", "admin", "pass") is None

    def test_returns_none_when_no_user(self):
        assert get_unifi_protect("http://protect:443", "", "pass") is None

    @patch("server.integrations.httpx.Client")
    def test_returns_data_on_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        login_resp = _mock_response(json_data={"id": "user1"})
        cam_resp = _mock_response(json_data=[
            {"name": "Front Door", "isRecording": True, "recordingSettings": {"mode": "always"}},
            {"name": "Backyard", "isRecording": False, "recordingSettings": {"mode": "never"}},
            {"name": "Garage", "isRecording": True, "recordingSettings": {"mode": "detections"}},
        ])
        mock_client.post.return_value = login_resp
        mock_client.get.return_value = cam_resp

        result = get_unifi_protect("http://protect:443", "admin", "pass")
        assert result is not None
        assert result["status"] == "online"
        assert result["cameras"] == 3
        assert result["recording"] == 2  # Front Door + Garage

    @patch("server.integrations.httpx.Client")
    def test_returns_none_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPError("fail")
        assert get_unifi_protect("http://protect:443", "admin", "pass") is None


# ===========================================================================
# 17. PiKVM
# ===========================================================================

class TestPikvm:
    def test_returns_none_when_no_url(self):
        assert get_pikvm("", "admin", "admin") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {"result": {"hw": {"platform": {"type": "rpi4"}}}}
        result = get_pikvm("http://pikvm:443", "admin", "admin")
        assert result is not None
        assert result["status"] == "online"
        assert result["online"] is True

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_pikvm("http://pikvm:443", "admin", "admin") is None


# ===========================================================================
# 18. Kubernetes
# ===========================================================================

class TestK8s:
    def test_returns_none_when_no_url(self):
        assert get_k8s("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_k8s("http://k8s:6443", "") is None

    @patch("server.integrations.httpx.get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = _mock_response(json_data={
            "items": [
                {
                    "metadata": {"name": "pod1", "namespace": "default"},
                    "status": {"phase": "Running"},
                },
                {
                    "metadata": {"name": "pod2", "namespace": "kube-system"},
                    "status": {"phase": "Running"},
                },
                {
                    "metadata": {"name": "pod3", "namespace": "default"},
                    "status": {"phase": "Pending"},
                },
            ],
        })
        result = get_k8s("http://k8s:6443", "bearer-token")
        assert result is not None
        assert result["status"] == "online"
        assert result["pods"] == 3
        assert result["running"] == 2
        assert result["namespaces"] == 2

    @patch("server.integrations.httpx.get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_k8s("http://k8s:6443", "token") is None


# ===========================================================================
# 19. Gitea
# ===========================================================================

class TestGitea:
    def test_returns_none_when_no_url(self):
        assert get_gitea("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_gitea("http://gitea:3000", "") is None

    @patch("server.integrations._client")
    def test_returns_data_on_success(self, mock_client):
        resp = _mock_response(
            json_data={"data": [{"id": 1}]},
            headers={"x-total-count": "42"},
        )
        mock_client.get.return_value = resp
        result = get_gitea("http://gitea:3000", "token")
        assert result is not None
        assert result["status"] == "online"
        assert result["repos"] == 42

    @patch("server.integrations._client")
    def test_returns_none_on_error(self, mock_client):
        mock_client.get.side_effect = httpx.HTTPError("fail")
        assert get_gitea("http://gitea:3000", "token") is None

    @patch("server.integrations._client")
    def test_falls_back_to_body_when_no_header(self, mock_client):
        resp = _mock_response(
            json_data={"data": [{"id": 1}, {"id": 2}]},
            headers={},  # no x-total-count
        )
        mock_client.get.return_value = resp
        result = get_gitea("http://gitea:3000", "token")
        assert result is not None
        assert result["repos"] == 2


# ===========================================================================
# 20. GitLab
# ===========================================================================

class TestGitlab:
    def test_returns_none_when_no_url(self):
        assert get_gitlab("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_gitlab("http://gitlab:443", "") is None

    @patch("server.integrations._client")
    def test_returns_data_on_success(self, mock_client):
        resp = _mock_response(
            json_data=[],
            headers={"x-total": "55"},
        )
        mock_client.get.return_value = resp
        result = get_gitlab("http://gitlab:443", "private-token")
        assert result is not None
        assert result["status"] == "online"
        assert result["projects"] == 55

    @patch("server.integrations._client")
    def test_returns_none_on_error(self, mock_client):
        mock_client.get.side_effect = httpx.HTTPError("fail")
        assert get_gitlab("http://gitlab:443", "token") is None


# ===========================================================================
# 21. GitHub
# ===========================================================================

class TestGithub:
    def test_returns_none_when_no_token(self):
        assert get_github("") is None

    @patch("server.integrations._client")
    def test_returns_data_on_success(self, mock_client):
        resp = _mock_response(json_data=[
            {"id": 1, "full_name": "user/repo1"},
            {"id": 2, "full_name": "user/repo2"},
            {"id": 3, "full_name": "user/repo3"},
        ])
        mock_client.get.return_value = resp
        result = get_github("ghp_xxxx")
        assert result is not None
        assert result["status"] == "online"
        assert result["repos"] == 3

    @patch("server.integrations._client")
    def test_returns_none_on_error(self, mock_client):
        mock_client.get.side_effect = httpx.HTTPError("fail")
        assert get_github("ghp_xxxx") is None


# ===========================================================================
# 22. Paperless-ngx
# ===========================================================================

class TestPaperless:
    def test_returns_none_when_no_url(self):
        assert get_paperless("", "token") is None

    def test_returns_none_when_no_token(self):
        assert get_paperless("http://paperless:8000", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {"count": 1234, "results": []}
        result = get_paperless("http://paperless:8000", "api-token")
        assert result is not None
        assert result["status"] == "online"
        assert result["documents"] == 1234

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_paperless("http://paperless:8000", "token") is None


# ===========================================================================
# 23. Vaultwarden
# ===========================================================================

class TestVaultwarden:
    def test_returns_none_when_no_url(self):
        assert get_vaultwarden("", "admin-token") is None

    def test_returns_none_when_no_admin_token(self):
        assert get_vaultwarden("http://vw:80", "") is None

    @patch("server.integrations._client")
    def test_returns_data_on_success(self, mock_client):
        resp = _mock_response(json_data=[], status_code=200)
        mock_client.get.return_value = resp
        result = get_vaultwarden("http://vw:80", "admin-token")
        assert result is not None
        assert result["status"] == "online"

    @patch("server.integrations._client")
    def test_returns_none_on_error(self, mock_client):
        mock_client.get.side_effect = httpx.HTTPError("fail")
        assert get_vaultwarden("http://vw:80", "admin-token") is None


# ===========================================================================
# 24. Weather (OpenWeatherMap)
# ===========================================================================

class TestWeather:
    def test_returns_none_when_no_api_key(self):
        assert get_weather("", "London") is None

    def test_returns_none_when_no_city(self):
        assert get_weather("owm-key", "") is None

    @patch("server.integrations._http_get")
    def test_returns_data_on_success(self, mock_get):
        mock_get.return_value = {
            "weather": [{"description": "clear sky", "icon": "01d"}],
            "main": {"temp": 22.5, "feels_like": 21.3, "humidity": 55},
            "name": "London",
        }
        result = get_weather("owm-key", "London")
        assert result is not None
        assert result["status"] == "online"
        assert result["temp"] == 22.5
        assert result["feels_like"] == 21.3
        assert result["humidity"] == 55
        assert result["description"] == "clear sky"
        assert result["icon"] == "01d"
        assert result["city"] == "London"

    @patch("server.integrations._http_get")
    def test_returns_none_on_error(self, mock_get):
        mock_get.side_effect = httpx.HTTPError("fail")
        assert get_weather("owm-key", "London") is None
