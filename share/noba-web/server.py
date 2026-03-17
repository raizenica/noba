#!/usr/bin/env python3
"""Nobara Command Center – Backend v1.1.1"""

import glob
import hashlib
import http.server
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

# ── Config ────────────────────────────────────────────────────────────────────
VERSION        = '1.1.1'
PORT           = int(os.environ.get('PORT', 8080))
HOST           = os.environ.get('HOST', '0.0.0.0')
SCRIPT_DIR     = os.environ.get('NOBA_SCRIPT_DIR', os.path.expanduser('~/.local/bin'))
LOG_DIR        = os.path.expanduser('~/.local/share')
PID_FILE       = os.environ.get('PID_FILE', '/tmp/noba-web-server.pid')
ACTION_LOG     = '/tmp/noba-action.log'
AUTH_CONFIG    = os.path.expanduser('~/.config/noba-web/auth.conf')
NOBA_YAML      = os.environ.get('NOBA_CONFIG', os.path.expanduser('~/.config/noba/config.yaml'))
MAX_BODY_BYTES = 64 * 1024  # 64 KiB – guard against oversized POST bodies
TOKEN_TTL_H    = 24
STATS_INTERVAL = 5          # background collector cadence (seconds)

SCRIPT_MAP = {
    'backup':        'backup-to-nas.sh',
    'verify':        'backup-verifier.sh',
    'organize':      'organize-downloads.sh',
    'diskcheck':     'disk-sentinel.sh',
    'check_updates': 'noba-update.sh',
}
ALLOWED_ACTIONS = frozenset({'start', 'stop', 'restart'})

_server_start_time = time.time()
_shutdown_flag     = threading.Event()

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
try:
    logging.basicConfig(
        filename=os.path.join(LOG_DIR, 'noba-web-server.log'),
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('noba')

ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub('', s)

def _read_file(path: str, default: str = '') -> str:
    """Safely read a file, ensuring descriptor closure."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return default

# ── Auth ──────────────────────────────────────────────────────────────────────
_tokens_lock = threading.Lock()
_tokens: dict = {}  # token → expiry datetime

def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    if stored.startswith('pbkdf2:'):
        parts = stored.split(':', 2)
        if len(parts) != 3:
            return False
        _, salt, expected = parts
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000)
        return secrets.compare_digest(expected, dk.hex())
    if ':' not in stored:
        return False
    salt, expected = stored.split(':', 1)
    actual = hashlib.sha256((salt + password).encode()).hexdigest()
    return secrets.compare_digest(expected, actual)

_user_cache: tuple | None = None
_user_cache_t: float = 0.0
_user_cache_lock = threading.Lock()
_USER_CACHE_TTL  = 30.0

def load_user() -> tuple | None:
    global _user_cache, _user_cache_t
    with _user_cache_lock:
        if time.time() - _user_cache_t < _USER_CACHE_TTL:
            return _user_cache
    if not os.path.exists(AUTH_CONFIG):
        return None
    try:
        with open(AUTH_CONFIG) as f:
            line = f.readline().strip()
        result = None
        if ':' in line:
            username, rest = line.split(':', 1)
            h = rest.rsplit(':', 1)[0] if rest.count(':') >= 2 else rest
            result = (username, h)
        with _user_cache_lock:
            _user_cache  = result
            _user_cache_t = time.time()
        return result
    except Exception as e:
        logger.warning('Could not read auth config: %s', e)
    return None

def generate_token() -> str:
    token = secrets.token_urlsafe(32)
    with _tokens_lock:
        _tokens[token] = datetime.now() + timedelta(hours=TOKEN_TTL_H)
    return token

def validate_token(token: str) -> bool:
    with _tokens_lock:
        expiry = _tokens.get(token)
        if expiry and expiry > datetime.now():
            return True
        _tokens.pop(token, None)
    return False

def revoke_token(token: str) -> None:
    with _tokens_lock:
        _tokens.pop(token, None)

def authenticate_request(headers, query=None) -> bool:
    auth = headers.get('Authorization', '')
    if auth.startswith('Bearer ') and validate_token(auth[7:]):
        return True
    if query and 'token' in query and validate_token(query['token'][0]):
        return True
    return False

def _token_cleanup_loop() -> None:
    while not _shutdown_flag.wait(300):
        now = datetime.now()
        with _tokens_lock:
            expired = [t for t, exp in list(_tokens.items()) if exp <= now]
            for t in expired:
                del _tokens[t]
        if expired:
            logger.info('Cleaned up %d expired token(s)', len(expired))

# ── Rate limiter ──────────────────────────────────────────────────────────────
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_s: int = 60, lockout_s: int = 300):
        self._lock      = threading.Lock()
        self._attempts: dict = {}
        self._lockouts: dict = {}
        self.max_attempts = max_attempts
        self.window_s     = window_s
        self.lockout_s    = lockout_s

    def is_locked(self, ip: str) -> bool:
        with self._lock:
            expiry = self._lockouts.get(ip)
            if expiry and datetime.now() < expiry:
                return True
            self._lockouts.pop(ip, None)
        return False

    def record_failure(self, ip: str) -> bool:
        now = datetime.now()
        with self._lock:
            cutoff   = now - timedelta(seconds=self.window_s)
            attempts = [t for t in self._attempts.get(ip, []) if t > cutoff]
            attempts.append(now)
            self._attempts[ip] = attempts
            if len(attempts) >= self.max_attempts:
                self._lockouts[ip] = now + timedelta(seconds=self.lockout_s)
                self._attempts.pop(ip, None)
                logger.warning('Login lockout applied to %s', ip)
                return True
        return False

    def reset(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)
            self._lockouts.pop(ip, None)

_rate_limiter = LoginRateLimiter()

# ── YAML helpers ──────────────────────────────────────────────────────────────
def read_yaml_settings() -> dict:
    defaults: dict = {
        'piholeUrl': None, 'piholeToken': None,
        'monitoredServices': None, 'radarIps': None, 'bookmarksStr': None,
    }
    if not os.path.exists(NOBA_YAML):
        return defaults
    try:
        r = subprocess.run(
            ['yq', 'eval', '-o=json', '.web', NOBA_YAML],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            web = json.loads(r.stdout)
            if isinstance(web, dict):
                for k in defaults:
                    if k in web:
                        defaults[k] = web[k]
    except Exception as e:
        logger.warning('Failed to read YAML settings: %s', e)
    return defaults

def write_yaml_settings(settings: dict) -> bool:
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            tmp.write('web:\n')
            for k, v in settings.items():
                if isinstance(v, str):
                    v = json.dumps(v)
                tmp.write(f'  {k}: {v}\n')
            tmp_path = tmp.name

        if os.path.exists(NOBA_YAML):
            backup = f'{NOBA_YAML}.bak.{int(time.time())}'
            try:
                shutil.copy2(NOBA_YAML, backup)
            except Exception as be:
                logger.warning('Could not create YAML backup: %s', be)

            r = subprocess.run(
                ['yq', 'eval-all', 'select(fileIndex==0) * select(fileIndex==1)',
                 NOBA_YAML, tmp_path],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                raise RuntimeError(f'yq merge failed: {r.stderr.strip()}')
            with open(NOBA_YAML, 'w') as f:
                f.write(r.stdout)
        else:
            os.makedirs(os.path.dirname(NOBA_YAML), exist_ok=True)
            with open(tmp_path) as src, open(NOBA_YAML, 'w') as dst:
                dst.write(src.read())

        return True
    except Exception as e:
        logger.exception('Failed to write YAML settings: %s', e)
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# ── Validation ────────────────────────────────────────────────────────────────
_SERVICE_NAME_RE = re.compile(r'^[a-zA-Z0-9_.@-]+$')

def validate_service_name(name: str) -> bool:
    return bool(_SERVICE_NAME_RE.match(name))

def validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

# ── TTL cache ─────────────────────────────────────────────────────────────────
class TTLCache:
    def __init__(self) -> None:
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float = 30) -> object:
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry['t']) < ttl:
                return entry['v']
        return None

    def set(self, key: str, val: object) -> None:
        with self._lock:
            self._store[key] = {'v': val, 't': time.time()}

_cache      = TTLCache()
_state_lock = threading.Lock()
_cpu_history: deque = deque(maxlen=20)
_cpu_prev    = None
_net_prev    = None
_net_prev_t  = None

# ── Subprocess helper ─────────────────────────────────────────────────────────
def run(cmd: list, timeout: float = 3, cache_key: str | None = None,
        cache_ttl: float = 30, ignore_rc: bool = False) -> str:
    if cache_key:
        hit = _cache.get(cache_key, cache_ttl)
        if hit is not None:
            return hit
    try:
        r   = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip() if (r.returncode == 0 or ignore_rc) else ''
        if cache_key and out:
            _cache.set(cache_key, out)
        return out
    except subprocess.TimeoutExpired:
        logger.warning('Command timed out after %.1fs: %s', timeout, ' '.join(str(c) for c in cmd))
        return ''
    except Exception as e:
        logger.debug('Command failed %s: %s', cmd, e)
        return ''

# ── Stat collectors ───────────────────────────────────────────────────────────
def human_bps(bps: float) -> str:
    for unit in ('B/s', 'KB/s', 'MB/s', 'GB/s'):
        if bps < 1024:
            return f'{bps:.1f} {unit}'
        bps /= 1024
    return f'{bps:.1f} TB/s'

def get_cpu_percent() -> float:
    global _cpu_prev
    with _state_lock:
        try:
            line = _read_file('/proc/stat', '')
            fields = list(map(int, line.split('\n')[0].split()[1:]))
            idle   = fields[3] + fields[4]
            total  = sum(fields)
            if _cpu_prev is None:
                _cpu_prev = (total, idle)
                return 0.0
            dt = total - _cpu_prev[0]
            di = idle  - _cpu_prev[1]
            _cpu_prev = (total, idle)
            pct = round(100.0 * (1.0 - di / dt) if dt > 0 else 0.0, 1)
            _cpu_history.append(pct)
            return pct
        except Exception:
            return 0.0

def get_net_io() -> tuple:
    global _net_prev, _net_prev_t
    with _state_lock:
        try:
            lines = _read_file('/proc/net/dev').splitlines()
            rx = tx = 0
            for line in lines[2:]:
                parts = line.split()
                if len(parts) > 9 and not parts[0].startswith('lo'):
                    rx += int(parts[1])
                    tx += int(parts[9])
            now = time.time()
            if _net_prev is None:
                _net_prev  = (rx, tx)
                _net_prev_t = now
                return 0.0, 0.0
            dt = now - _net_prev_t
            if dt < 0.05:
                return 0.0, 0.0
            rx_bps = max(0.0, (rx - _net_prev[0]) / dt)
            tx_bps = max(0.0, (tx - _net_prev[1]) / dt)
            _net_prev   = (rx, tx)
            _net_prev_t = now
            return rx_bps, tx_bps
        except Exception:
            return 0.0, 0.0

def ping_host(ip: str) -> tuple:
    ip = ip.strip()
    if not validate_ip(ip):
        return ip, False, 0
    try:
        t0 = time.time()
        r  = subprocess.run(['ping', '-c', '1', '-W', '1', ip], capture_output=True, timeout=2.5)
        return ip, r.returncode == 0, round((time.time() - t0) * 1000)
    except Exception:
        return ip, False, 0

def get_service_status(svc: str) -> tuple:
    svc = svc.strip()
    if not validate_service_name(svc):
        return 'invalid', False
    for scope, is_user in ((['--user'], True), ([], False)):
        cmd = ['systemctl'] + scope + ['show', '-p', 'ActiveState,LoadState', svc]
        out = run(cmd, timeout=2)
        d   = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
        if d.get('LoadState') not in (None, '', 'not-found'):
            state = d.get('ActiveState', 'unknown')
            if state == 'inactive' and svc.endswith('.service'):
                timer_name = svc.replace('.service', '.timer')
                t = run(['systemctl'] + scope + ['show', '-p', 'ActiveState', timer_name], timeout=1)
                if 'ActiveState=active' in t:
                    return 'timer-active', is_user
            return state, is_user
    return 'not-found', False

def get_battery() -> dict:
    bats = glob.glob('/sys/class/power_supply/BAT*')
    if not bats:
        return {'percent': 100, 'status': 'Desktop', 'desktop': True, 'timeRemaining': ''}
    try:
        bat      = bats[0]
        pct      = int(_read_file(f'{bat}/capacity', '0'))
        stat     = _read_file(f'{bat}/status', 'Unknown')
        time_rem = ''
        try:
            current = int(_read_file(f'{bat}/current_now', '0'))
            if current > 0:
                if stat == 'Discharging':
                    hrs      = int(_read_file(f'{bat}/charge_now', '0')) / current
                    time_rem = f'{int(hrs)}h {int((hrs % 1) * 60)}m'
                else:
                    cfull    = int(_read_file(f'{bat}/charge_full', '0'))
                    charge   = int(_read_file(f'{bat}/charge_now', '0'))
                    hrs      = (cfull - charge) / current
                    time_rem = f'{int(hrs)}h {int((hrs % 1) * 60)}m to full'
        except Exception:
            pass
        return {'percent': pct, 'status': stat, 'desktop': False, 'timeRemaining': time_rem}
    except Exception:
        return {'percent': 0, 'status': 'Error', 'desktop': False, 'timeRemaining': ''}

def get_containers() -> list:
    for cmd in (
        ['podman', 'ps', '-a', '--format', 'json'],
        ['docker', 'ps', '-a', '--format', '{{json .}}'],
    ):
        out = run(cmd, timeout=4, cache_key=' '.join(cmd), cache_ttl=10)
        if not out:
            continue
        try:
            items = (json.loads(out) if out.lstrip().startswith('[')
                     else [json.loads(l) for l in out.splitlines() if l.strip()])
            result = []
            for c in items[:16]:
                name  = c.get('Names', c.get('Name', '?'))
                if isinstance(name, list):
                    name = name[0] if name else '?'
                image = c.get('Image', c.get('Repository', '?')).split('/')[-1][:32]
                state = (c.get('State', c.get('Status', '?')) or '?').lower().split()[0]
                result.append({
                    'name': name, 'image': image,
                    'state': state, 'status': c.get('Status', state),
                })
            return result
        except Exception:
            continue
    return []

def get_pihole(url: str, token: str) -> dict | None:
    if not url:
        return None
    base = url if url.startswith('http') else 'http://' + url
    base = base.rstrip('/').replace('/admin', '')

    def _get(endpoint: str, extra_headers: dict | None = None) -> dict:
        hdrs = {'User-Agent': f'noba-web/{VERSION}', 'Accept': 'application/json'}
        if extra_headers:
            hdrs.update(extra_headers)
        req = urllib.request.Request(base + endpoint, headers=hdrs)
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode())

    try:
        data = _get('/api/stats/summary', {'sid': token} if token else {})
        return {
            'queries': data.get('queries', {}).get('total', 0),
            'blocked': data.get('ads', {}).get('blocked', 0),
            'percent': round(data.get('ads', {}).get('percentage', 0.0), 1),
            'status':  data.get('gravity', {}).get('status', 'unknown'),
            'domains': f"{data.get('gravity', {}).get('domains_being_blocked', 0):,}",
        }
    except Exception:
        pass

    try:
        ep   = '/admin/api.php?summaryRaw' + (f'&auth={token}' if token else '')
        data = _get(ep)
        return {
            'queries': data.get('dns_queries_today', 0),
            'blocked': data.get('ads_blocked_today', 0),
            'percent': round(data.get('ads_percentage_today', 0), 1),
            'status':  data.get('status', 'enabled'),
            'domains': f"{data.get('domains_being_blocked', 0):,}",
        }
    except Exception:
        return None

# ── Stats assembly ──────────────────────────────
def _collect_system() -> dict:
    s: dict = {}
    try:
        for line in _read_file('/etc/os-release').splitlines():
            if line.startswith('PRETTY_NAME='):
                s['osName'] = line.split('=', 1)[1].strip().strip('"')
                break
    except Exception:
        s['osName'] = 'Linux'

    s['kernel']    = run(['uname', '-r'],  cache_key='uname-r',  cache_ttl=3600)
    s['hostname']  = run(['hostname'],     cache_key='hostname',  cache_ttl=3600)
    s['defaultIp'] = run(
        ['bash', '-c', "ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \\K[\\d.]+'"],
        timeout=1,
    )
    try:
        up_s = float(_read_file('/proc/uptime', '0 0').split()[0])
        d, rem = divmod(int(up_s), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        s['uptime']  = (f'{d}d ' if d else '') + f'{h}h {m}m'
        s['loadavg'] = ' '.join(_read_file('/proc/loadavg', '0 0 0').split()[:3])
        mm    = {l.split(':')[0]: int(l.split()[1]) for l in _read_file('/proc/meminfo').splitlines() if ':' in l}
        tot   = mm.get('MemTotal', 0) // 1024
        avail = mm.get('MemAvailable', 0) // 1024
        used  = tot - avail
        s['memory']     = f'{used} MiB / {tot} MiB'
        s['memPercent'] = round(100 * used / tot) if tot > 0 else 0
    except Exception:
        s.setdefault('uptime', '--')
        s.setdefault('loadavg', '--')
        s.setdefault('memPercent', 0)
    return s

def _collect_hardware() -> dict:
    s: dict = {}
    s['hwCpu'] = run(
        ['bash', '-c', "lscpu | grep 'Model name' | head -1 | cut -d: -f2 | xargs"],
        cache_key='lscpu', cache_ttl=3600,
    )
    raw_gpu = run(
        ['bash', '-c', "lspci | grep -i 'vga\\|3d' | cut -d: -f3"],
        cache_key='lspci', cache_ttl=3600,
    )
    s['hwGpu'] = raw_gpu.replace('\n', '<br>') if raw_gpu else 'Unknown GPU'

    sensors = run(['sensors'], timeout=2, cache_key='sensors', cache_ttl=5)
    m = re.search(r'(?:Tctl|Package id \d+|Core 0|temp1).*?\+?(\d+\.?\d*)[°℃]', sensors)
    s['cpuTemp'] = f'{int(float(m.group(1)))}°C' if m else 'N/A'

    gpu_t = run(
        ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
        timeout=2, cache_key='nvidia-temp', cache_ttl=5,
    )
    if not gpu_t:
        raw = run(
            ['bash', '-c',
             'cat /sys/class/drm/card*/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1'],
            timeout=1,
        )
        gpu_t = f'{int(raw) // 1000}°C' if raw else 'N/A'
    else:
        gpu_t = f'{gpu_t}°C'
    s['gpuTemp'] = gpu_t
    s['battery'] = get_battery()
    return s

def _collect_storage() -> dict:
    disks = []
    for line in run(['df', '-BM'], cache_key='df', cache_ttl=10).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith('/dev/'):
            continue
        mount = parts[5]
        if any(mount.startswith(p) for p in ('/var/lib/snapd', '/boot', '/run', '/snap')):
            continue
        try:
            pct = int(parts[4].replace('%', ''))
            disks.append({
                'mount':    mount,
                'percent':  pct,
                'barClass': 'danger' if pct >= 90 else 'warning' if pct >= 75 else 'success',
                'size':     parts[1].replace('M', ' MiB'),
                'used':     parts[2].replace('M', ' MiB'),
            })
        except (ValueError, IndexError):
            pass

    pools = []
    for line in run(
        ['zpool', 'list', '-H', '-o', 'name,health'],
        timeout=3, cache_key='zpool', cache_ttl=15,
    ).splitlines():
        if '\t' in line:
            n, h = line.split('\t', 1)
            pools.append({'name': n.strip(), 'health': h.strip()})

    return {'disks': disks, 'zfs': {'pools': pools}}

def _collect_network() -> dict:
    rx_bps, tx_bps = get_net_io()
    def parse_ps(out: str) -> list:
        result = []
        for line in out.splitlines()[1:6]:
            parts = line.strip().rsplit(None, 1)
            if len(parts) == 2 and parts[1] not in ('%CPU', '%MEM'):
                result.append({'name': parts[0][:16], 'val': parts[1] + '%'})
        return result

    return {
        'netRx':  human_bps(rx_bps),
        'netTx':  human_bps(tx_bps),
        'topCpu': parse_ps(run(['ps', 'ax', '--format', 'comm,%cpu', '--sort', '-%cpu'], timeout=2)),
        'topMem': parse_ps(run(['ps', 'ax', '--format', 'comm,%mem', '--sort', '-%mem'], timeout=2)),
    }

def _build_alerts(stats: dict) -> list:
    alerts = []
    cpu = stats.get('cpuPercent', 0)
    if cpu > 90:
        alerts.append({'level': 'danger',  'msg': f'CPU critical: {cpu}%'})
    elif cpu > 75:
        alerts.append({'level': 'warning', 'msg': f'CPU high: {cpu}%'})

    ct = stats.get('cpuTemp', 'N/A')
    if ct != 'N/A':
        t = int(ct.replace('°C', ''))
        if t > 85:
            alerts.append({'level': 'danger',  'msg': f'CPU temp critical: {t}°C'})
        elif t > 70:
            alerts.append({'level': 'warning', 'msg': f'CPU temp elevated: {t}°C'})

    for disk in stats.get('disks', []):
        p = disk.get('percent', 0)
        if p >= 90:
            alerts.append({'level': 'danger',  'msg': f"Disk {disk['mount']} at {p}%"})
        elif p >= 80:
            alerts.append({'level': 'warning', 'msg': f"Disk {disk['mount']} at {p}%"})

    for svc in stats.get('services', []):
        if svc.get('status') == 'failed':
            alerts.append({'level': 'danger', 'msg': f"Service failed: {svc['name']}"})

    return alerts

_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix='noba-worker')

def collect_stats(qs: dict) -> dict:
    stats: dict = {'timestamp': datetime.now().strftime('%H:%M:%S')}
    stats.update(_collect_system())
    stats.update(_collect_hardware())
    stats.update(_collect_storage())
    stats['cpuPercent'] = get_cpu_percent()
    with _state_lock:
        stats['cpuHistory'] = list(_cpu_history)
    stats.update(_collect_network())

    svc_list = [s.strip() for s in qs.get('services', [''])[0].split(',') if s.strip()]
    ip_list  = [ip.strip() for ip in qs.get('radar',    [''])[0].split(',') if ip.strip()]
    ph_url   = qs.get('pihole',    [''])[0]
    ph_tok   = qs.get('piholetok', [''])[0]

    svc_futs  = {_pool.submit(get_service_status, s): s for s in svc_list}
    ping_futs = {_pool.submit(ping_host, ip): ip for ip in ip_list}
    ph_fut    = _pool.submit(get_pihole, ph_url, ph_tok) if ph_url else None
    ct_fut    = _pool.submit(get_containers)

    services = []
    for fut, svc in svc_futs.items():
        try:
            status, is_user = fut.result(timeout=4)
        except Exception:
            status, is_user = 'error', False
        services.append({'name': svc, 'status': status, 'is_user': is_user})
    stats['services'] = services

    radar = []
    for fut, ip in ping_futs.items():
        try:
            ip_r, up, ms = fut.result(timeout=4)
            radar.append({'ip': ip_r, 'status': 'Up' if up else 'Down', 'ms': ms if up else 0})
        except Exception:
            radar.append({'ip': ip, 'status': 'Down', 'ms': 0})
    stats['radar'] = radar

    try:
        stats['pihole'] = ph_fut.result(timeout=4) if ph_fut else None
    except Exception:
        stats['pihole'] = None

    try:
        stats['containers'] = ct_fut.result(timeout=5)
    except Exception:
        stats['containers'] = []

    stats['alerts'] = _build_alerts(stats)
    return stats

# ── Background collector ──────────────────────────────────────────────────────
class BackgroundCollector:
    def __init__(self, interval: int = STATS_INTERVAL) -> None:
        self._lock     = threading.Lock()
        self._latest:  dict = {}
        self._qs:      dict = {}
        self._interval = interval

    def update_qs(self, qs: dict) -> None:
        with self._lock:
            self._qs = dict(qs)

    def get(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name='stats-collector').start()

    def _loop(self) -> None:
        while not _shutdown_flag.is_set():
            try:
                with self._lock:
                    qs = dict(self._qs)
                data = collect_stats(qs)
                with self._lock:
                    self._latest = data
            except Exception as e:
                logger.warning('Collector error: %s', e)
            _shutdown_flag.wait(self._interval)

_bg = BackgroundCollector()

# ── HTTP handler ──────────────────────────────────────────────────────────────
_SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options':        'SAMEORIGIN',
    'Referrer-Policy':        'same-origin',
}

_active_job: dict | None = None
_job_lock = threading.Lock()

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory='.', **kwargs)

    def log_message(self, fmt, *args):
        pass

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else '0.0.0.0'

    def _json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            self._json({'error': 'Request body too large'}, 413)
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._json({'error': 'Invalid JSON'}, 400)
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        path   = parsed.path

        if path in ('/', '/index.html'):
            super().do_GET()
            return

        if path == '/api/health':
            self._json({
                'status':   'ok',
                'version':  VERSION,
                'uptime_s': round(time.time() - _server_start_time),
            })
            return

        if not authenticate_request(self.headers, qs):
            self.send_error(401, 'Unauthorized')
            return

        if path == '/api/stats':
            _bg.update_qs(qs)
            try:
                self._json(_bg.get() or collect_stats(qs))
            except Exception as e:
                logger.exception('Error in /api/stats')
                self._json({'error': str(e)}, 500)

        elif path == '/api/settings':
            self._json(read_yaml_settings())

        elif path == '/api/stream':
            _bg.update_qs(qs)
            self.send_response(200)
            self.send_header('Content-Type',  'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection',    'keep-alive')
            self.end_headers()
            last_heartbeat = time.time()
            try:
                first = _bg.get() or collect_stats(qs)
                self.wfile.write(f'data: {json.dumps(first)}\n\n'.encode())
                self.wfile.flush()
                while not _shutdown_flag.is_set():
                    _shutdown_flag.wait(5)
                    if _shutdown_flag.is_set():
                        break
                    now  = time.time()
                    data = _bg.get()
                    if data:
                        self.wfile.write(f'data: {json.dumps(data)}\n\n'.encode())
                        self.wfile.flush()
                    if now - last_heartbeat >= 15:
                        self.wfile.write(b': ping\n\n')
                        self.wfile.flush()
                        last_heartbeat = now
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            except Exception as e:
                logger.warning('SSE error: %s', e)

        elif path == '/api/log-viewer':
            log_type = qs.get('type', ['syserr'])[0]
            if log_type == 'syserr':
                text = run(['journalctl', '-p', '3', '-n', '25', '--no-pager'], timeout=4)
            elif log_type == 'action':
                text = strip_ansi(_read_file(ACTION_LOG, 'No recent actions.'))
            elif log_type == 'backup':
                try:
                    lines = _read_file(os.path.join(LOG_DIR, 'backup-to-nas.log'), 'No backup log found.').splitlines()
                    text  = strip_ansi('\n'.join(lines[-30:]))
                except Exception:
                    text = 'No backup log found.'
            else:
                text = 'Unknown log type.'
            body = (text or 'Empty.').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/action-log':
            text = strip_ansi(_read_file(ACTION_LOG, 'Waiting for output…'))
            body = text.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == '/api/run-status':
            with _job_lock:
                self._json(dict(_active_job) if _active_job else {'status': 'idle'})

        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split('?')[0]
        ip   = self._client_ip()

        if path == '/api/login':
            if _rate_limiter.is_locked(ip):
                self._json({'error': 'Too many failed attempts. Try again shortly.'}, 429)
                return
            body = self._read_body()
            if body is None:
                return
            try:
                user     = load_user()
                username = body.get('username', '')
                password = body.get('password', '')
                if user and secrets.compare_digest(username, user[0]) and \
                        verify_password(user[1], password):
                    _rate_limiter.reset(ip)
                    self._json({'token': generate_token()})
                else:
                    locked = _rate_limiter.record_failure(ip)
                    msg    = ('Too many failed attempts. Try again shortly.'
                              if locked else 'Invalid credentials')
                    self._json({'error': msg}, 401)
            except Exception as e:
                logger.exception('Login error')
                self._json({'error': str(e)}, 500)
            return

        if path == '/api/logout':
            qs    = parse_qs(urlparse(self.path).query)
            auth  = self.headers.get('Authorization', '')
            token = auth[7:] if auth.startswith('Bearer ') else qs.get('token', [''])[0]
            if token:
                revoke_token(token)
            self._json({'status': 'ok'})
            return

        if not authenticate_request(self.headers):
            self.send_error(401, 'Unauthorized')
            return

        if path == '/api/settings':
            body = self._read_body()
            if body is None:
                return
            ok = write_yaml_settings(body)
            self._json(
                {'status': 'ok'} if ok else {'error': 'Failed to write settings'},
                200 if ok else 500,
            )

        elif path == '/api/run':
            body = self._read_body()
            if body is None:
                return
            script = body.get('script', '')

            with _job_lock:
                global _active_job
                if _active_job and _active_job.get('status') == 'running':
                    self._json({'success': False, 'error': 'A script is already running'})
                    return
                _active_job = {
                    'script':  script,
                    'status':  'running',
                    'started': datetime.now().isoformat(),
                }

            # Run synchronously in the request thread to keep frontend await perfectly synced
            status = 'error'
            p = None
            try:
                ts = datetime.now().strftime('%H:%M:%S')
                with open(ACTION_LOG, 'w') as f:
                    f.write(f'>> [{ts}] Initiating: {script}\n\n')

                if script == 'speedtest':
                    with open(ACTION_LOG, 'a') as f:
                        p = subprocess.Popen(['speedtest-cli', '--simple'], stdout=f, stderr=subprocess.STDOUT)
                elif script in SCRIPT_MAP:
                    sfile = os.path.join(SCRIPT_DIR, SCRIPT_MAP[script])
                    if os.path.isfile(sfile):
                        with open(ACTION_LOG, 'a') as f:
                            p = subprocess.Popen(
                                [sfile, '--verbose'], stdout=f, stderr=subprocess.STDOUT, cwd=SCRIPT_DIR,
                            )
                    else:
                        with open(ACTION_LOG, 'a') as f:
                            f.write(f'[ERROR] Script not found: {sfile}\n')
                        status = 'failed'
                else:
                    with open(ACTION_LOG, 'a') as f:
                        f.write(f'[ERROR] Unknown script: {script}\n')
                    status = 'failed'

                if p:
                    try:
                        p.wait(timeout=300)
                        status = 'done' if p.returncode == 0 else 'failed'
                    except subprocess.TimeoutExpired:
                        p.kill()  # Force process reap to prevent zombies
                        p.wait()
                        with open(ACTION_LOG, 'a') as f:
                            f.write('\n[ERROR] Script timed out after 300s. Process killed.\n')
                        status = 'timeout'

            except Exception as e:
                logger.exception('Script runner error: %s', e)
            finally:
                with open(ACTION_LOG, 'a') as f:
                    f.write(f'\n>> [{datetime.now().strftime("%H:%M:%S")}] {status.upper()}\n')
                with _job_lock:
                    if _active_job and _active_job.get('script') == script:
                        _active_job['status']  = status
                        _active_job['finished'] = datetime.now().isoformat()

            # Now we actually return the success key the frontend expects!
            self._json({'success': status == 'done', 'status': status, 'script': script})

        elif path == '/api/service-control':
            body = self._read_body()
            if body is None:
                return
            svc     = body.get('service', '').strip()
            action  = body.get('action', '').strip()
            is_user = bool(body.get('is_user', False))
            if action not in ALLOWED_ACTIONS:
                self._json({'success': False, 'error': f'Action "{action}" not allowed'})
                return
            if not svc:
                self._json({'success': False, 'error': 'No service name provided'})
                return
            if not validate_service_name(svc):
                self._json({'success': False, 'error': 'Invalid service name'})
                return
            cmd = (['systemctl', '--user', action, svc]
                   if is_user else ['sudo', '-n', 'systemctl', action, svc])
            try:
                r = subprocess.run(cmd, timeout=10, capture_output=True)
                self._json({'success': r.returncode == 0, 'stderr': r.stderr.decode().strip()})
            except Exception as e:
                self._json({'success': False, 'error': str(e)})

        else:
            self.send_error(404)


# ── Server ────────────────────────────────────────────────────────────────────
class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads      = True

_server = None

def _sigterm_handler(signum, frame) -> None:
    logger.info('SIGTERM received, shutting down…')
    _shutdown_flag.set()
    if _server:
        threading.Thread(target=_server.shutdown, daemon=True).start()

signal.signal(signal.SIGTERM, _sigterm_handler)

if __name__ == '__main__':
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        logger.warning('Could not write PID file: %s', e)

    _bg.start()
    threading.Thread(target=_token_cleanup_loop, daemon=True, name='token-cleanup').start()

    _server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info('Nobara v%s listening on http://%s:%d', VERSION, HOST, PORT)
    print(f'Noba backend v{VERSION} listening on http://{HOST}:{PORT}', file=sys.stderr)

    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Shutdown requested via KeyboardInterrupt')
    finally:
        _shutdown_flag.set()
        _server.shutdown()
        _pool.shutdown(wait=False)
        try:
            os.unlink(PID_FILE)
        except Exception:
            pass
        logger.info('Server stopped.')
