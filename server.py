"""OBS Remote: a tiny web server for the phone control page.

The page talks straight to obs-websocket (normally port 4455) on this PC, so this
server only hands out the files in www/. Python standard library only.

    python server.py            # serves on port 8765
    python server.py 9000       # another port
"""
import functools
import http.server
import os
import socket
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("OBS_REMOTE_PORT", "8765"))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quiet: one line per page load only
        if self.path in ("/", "/index.html") and sys.stderr:
            sys.stderr.write("%s  %s\n" % (self.address_string(), fmt % args))


def lan_ips():
    """This PC's LAN addresses, best guess first."""
    ips = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it only picks the outgoing interface
        ips.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


if __name__ == "__main__":
    try:
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), functools.partial(Handler, directory=ROOT))
    except OSError as e:
        sys.exit(f"Can't use port {PORT} ({e}). Is OBS Remote already running?")
    if sys.stdout:
        print("OBS Remote is running. On your phone (same Wi-Fi), open:")
        for ip in lan_ips():
            print(f"    http://{ip}:{PORT}/")
        print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
