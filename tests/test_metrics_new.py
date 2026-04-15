# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for v2.0.0 metric functions: cert expiry, domain expiry, VPN, governor, WOL, game probe."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


# ── Certificate expiry ───────────────────────────────────────────────────────
class TestCertExpiry:
    def test_returns_list(self):
        from server.metrics import check_cert_expiry
        assert check_cert_expiry([]) == []

    @patch("ssl.create_default_context")
    @patch("socket.socket")
    def test_valid_cert(self, mock_socket_cls, mock_ssl_ctx):
        mock_ctx = MagicMock()
        mock_ssl_ctx.return_value = mock_ctx

        mock_wrapped = MagicMock()
        mock_ctx.wrap_socket.return_value.__enter__ = MagicMock(return_value=mock_wrapped)
        mock_ctx.wrap_socket.return_value.__exit__ = MagicMock(return_value=False)

        mock_wrapped.getpeercert.return_value = {
            "notAfter": "Dec 31 23:59:59 2027 GMT",
            "issuer": ((("organizationName", "Test CA"),),),
        }

        from server.metrics import check_cert_expiry
        result = check_cert_expiry(["example.com"])
        assert len(result) == 1
        assert result[0]["host"] == "example.com"
        assert result[0]["days"] > 0
        assert result[0]["issuer"] == "Test CA"
        assert "error" not in result[0]

    def test_invalid_host(self):
        from server.metrics import check_cert_expiry
        result = check_cert_expiry(["nonexistent.invalid.host.test"])
        assert len(result) == 1
        assert "error" in result[0]


# ── Domain expiry ────────────────────────────────────────────────────────────
class TestDomainExpiry:
    def test_returns_list(self):
        from server.metrics import check_domain_expiry
        assert check_domain_expiry([]) == []

    @patch("server.metrics.network._run")
    def test_parses_whois(self, mock_run):
        mock_run.return_value = "Registry Expiry Date: 2026-12-31T00:00:00Z\n"
        from server.metrics import check_domain_expiry
        result = check_domain_expiry(["example.com"])
        assert len(result) == 1
        assert result[0]["days"] is not None
        assert result[0]["days"] > 0

    @patch("server.metrics.network._run")
    def test_no_expiry_found(self, mock_run):
        mock_run.return_value = "Some random whois output\n"
        from server.metrics import check_domain_expiry
        result = check_domain_expiry(["example.com"])
        assert "error" in result[0]

    @patch("server.metrics.network._run")
    def test_parses_dash_date_format(self, mock_run):
        mock_run.return_value = "Expiry Date: 2027-06-15\n"
        from server.metrics import check_domain_expiry
        result = check_domain_expiry(["example.com"])
        assert len(result) == 1
        assert result[0]["days"] is not None
        assert result[0]["days"] > 0

    @patch("server.metrics.network._run")
    def test_multiple_domains(self, mock_run):
        mock_run.side_effect = [
            "Registry Expiry Date: 2026-12-31T00:00:00Z\n",
            "Some random whois output\n",
        ]
        from server.metrics import check_domain_expiry
        result = check_domain_expiry(["good.com", "bad.com"])
        assert len(result) == 2
        assert result[0]["days"] is not None
        assert "error" in result[1]


# ── VPN / WireGuard status ───────────────────────────────────────────────────
class TestVpnStatus:
    @patch("server.metrics.network._run")
    def test_no_wireguard(self, mock_run):
        mock_run.return_value = ""
        from server.metrics import get_vpn_status
        assert get_vpn_status() is None

    @patch("server.metrics.network._run")
    def test_with_peers(self, mock_run):
        mock_run.return_value = (
            "wg0\tpubkey\tpsk\t1.2.3.4:51820\t10.0.0.0/24\t1234567890\t1000\t2000"
        )
        from server.metrics import get_vpn_status
        result = get_vpn_status()
        assert result is not None
        assert result["peer_count"] == 1
        assert result["peers"][0]["interface"] == "wg0"
        assert result["peers"][0]["endpoint"] == "1.2.3.4:51820"
        assert result["peers"][0]["rx_bytes"] == 1000
        assert result["peers"][0]["tx_bytes"] == 2000

    @patch("server.metrics.network._run")
    def test_endpoint_none(self, mock_run):
        mock_run.return_value = (
            "wg0\tpubkey\tpsk\t(none)\t10.0.0.0/24\t0\t0\t0"
        )
        from server.metrics import get_vpn_status
        result = get_vpn_status()
        assert result is not None
        assert result["peers"][0]["endpoint"] == ""
        assert result["peers"][0]["last_handshake"] == 0

    @patch("server.metrics.network._run")
    def test_multiple_peers(self, mock_run):
        mock_run.return_value = (
            "wg0\tpk1\tpsk\t1.2.3.4:51820\t10.0.0.0/24\t1234567890\t100\t200\n"
            "wg0\tpk2\tpsk\t5.6.7.8:51820\t10.0.1.0/24\t1234567890\t300\t400"
        )
        from server.metrics import get_vpn_status
        result = get_vpn_status()
        assert result is not None
        assert result["peer_count"] == 2

    @patch("server.metrics.network._run")
    def test_short_line_skipped(self, mock_run):
        mock_run.return_value = "wg0\tpubkey\tpsk"
        from server.metrics import get_vpn_status
        result = get_vpn_status()
        assert result is None


# ── CPU governor ─────────────────────────────────────────────────────────────
class TestCpuGovernor:
    def test_returns_string(self):
        from server.metrics import get_cpu_governor
        result = get_cpu_governor()
        assert isinstance(result, str)

    @patch("server.metrics.system._read_file")
    def test_returns_governor_value(self, mock_read):
        mock_read.return_value = "performance"
        from server.metrics import get_cpu_governor
        result = get_cpu_governor()
        assert result == "performance"

    @patch("server.metrics.system._read_file")
    def test_returns_unknown_when_missing(self, mock_read):
        mock_read.return_value = "unknown"
        from server.metrics import get_cpu_governor
        result = get_cpu_governor()
        assert result == "unknown"


# ── Wake-on-LAN ─────────────────────────────────────────────────────────────
class TestWol:
    def test_invalid_mac(self):
        from server.metrics import send_wol
        assert send_wol("invalid") is False
        assert send_wol("00:11:22") is False

    def test_invalid_hex_chars(self):
        from server.metrics import send_wol
        assert send_wol("ZZ:ZZ:ZZ:ZZ:ZZ:ZZ") is False

    @patch("server.metrics.services.socket")
    def test_valid_mac(self, mock_socket_mod):
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_DGRAM = 2
        mock_socket_mod.SOL_SOCKET = 1
        mock_socket_mod.SO_BROADCAST = 6
        from server.metrics import send_wol
        result = send_wol("00:11:22:33:44:55")
        assert result is True

    @patch("server.metrics.services.socket")
    def test_valid_mac_with_dashes(self, mock_socket_mod):
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_DGRAM = 2
        mock_socket_mod.SOL_SOCKET = 1
        mock_socket_mod.SO_BROADCAST = 6
        from server.metrics import send_wol
        result = send_wol("00-11-22-33-44-55")
        assert result is True


# ── Game server probe ────────────────────────────────────────────────────────
class TestGameServerProbe:
    @patch("server.metrics.services.socket")
    def test_online_server(self, mock_socket_mod):
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_STREAM = 1
        from server.metrics import probe_game_server
        result = probe_game_server("localhost", 8080)
        assert result["status"] == "online"
        assert result["host"] == "localhost"
        assert result["port"] == 8080
        assert result["ms"] >= 0

    def test_offline_server(self):
        from server.metrics import probe_game_server
        result = probe_game_server("192.0.2.1", 99999)
        assert result["status"] == "offline"
        assert result["ms"] == 0
        assert result["host"] == "192.0.2.1"
        assert result["port"] == 99999

    @patch("server.metrics.services.socket")
    def test_connection_refused(self, mock_socket_mod):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("refused")
        mock_socket_mod.socket.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = MagicMock(return_value=False)
        mock_socket_mod.AF_INET = 2
        mock_socket_mod.SOCK_STREAM = 1
        from server.metrics import probe_game_server
        result = probe_game_server("localhost", 9999)
        assert result["status"] == "offline"
