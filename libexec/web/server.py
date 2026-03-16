import http.server, socketserver, json, os, subprocess, threading, time, ssl, logging, secrets

# --- Configuration ---
HOST, PORT = "0.0.0.0", 8080
TOKEN_FILE = os.path.expanduser("~/.config/noba/token.json")
LOG_FILE = os.path.expanduser("~/.local/state/noba/organize.log")
USE_HTTPS = os.getenv("NOBA_HTTPS") == "1"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger("noba-core")

# --- Native Stats Readers ---
def get_stats():
    stats = {}
    try:
        with open("/proc/loadavg") as f: stats["CPU_Load"] = f.read().split()[0] + " %"
        with open("/proc/meminfo") as f:
            lines = f.readlines()
            total = int(lines[0].split()[1])
            free = int(lines[1].split()[1])
            stats["Memory"] = f"{int((total-free)/total*100)}%"
        with open("/proc/uptime") as f:
            up = float(f.readline().split()[0])
            stats["Uptime"] = f"{int(up // 86400)}d {int((up % 86400) // 3600)}h"
    except: pass
    return stats

# --- Request Handler ---
class Handler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = json.loads(self.rfile.read(content_length).decode())
        
        if self.path == "/api/login":
            # In production, check against your PBKDF2 hash here. 
            # For now, we allow the session if password matches your logic.
            token = secrets.token_hex(16)
            self._send_json({"token": token})
            
        elif self.path == "/api/run":
            action = body.get("action")
            script = os.path.expanduser(f"~/.local/libexec/noba/{action}-downloads.sh" if action == "organize" else f"~/.local/libexec/noba/{action}-script.sh")
            subprocess.Popen(["bash", script], start_new_session=True)
            self._send_json({"status": "started"})

    def do_GET(self):
        if self.path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            while True:
                data = get_stats()
                self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, "r") as f:
                        lines = f.readlines()[-1:]
                        for l in lines:
                            self.wfile.write(f"event: log\ndata: {l.strip()}\n\n".encode())
                time.sleep(2)
        else:
            path = os.path.join(os.getcwd(), "index.html")
            with open(path, 'rb') as f:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f.read())

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if USE_HTTPS:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.getenv("NOBA_CERT"), os.getenv("NOBA_KEY"))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    
    logger.info(f"NobaCore live at {'https' if USE_HTTPS else 'http'}://{HOST}:{PORT}")
    server.serve_forever()
