#!/usr/bin/env python3
"""GitHub webhook listener for instant deploys.
Binds to 127.0.0.1:9000 (localhost only — nginx proxies from port 80).
Verifies GitHub HMAC-SHA256 signature before triggering deploy.
"""

import hashlib
import hmac
import json
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

SECRET_FILE = "/opt/.webhook_secret"
DEPLOY_SCRIPT = "/opt/auto_deploy_general.sh"
LOG_FILE = "/var/log/webhook-deploy.log"
START_TIME = time.time()


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}: {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def read_secret():
    try:
        with open(SECRET_FILE) as f:
            return f.read().strip().encode()
    except FileNotFoundError:
        log(f"ERROR: Secret file {SECRET_FILE} not found")
        return None


def verify_signature(payload, signature_header, secret):
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            uptime = int(time.time() - START_TIME)
            body = json.dumps({"status": "ok", "uptime_seconds": uptime})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        secret = read_secret()
        if not secret:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Server misconfigured")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(content_length)
        signature = self.headers.get("X-Hub-Signature-256", "")

        if not verify_signature(payload, signature, secret):
            log("REJECTED: Invalid signature")
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

        ref = data.get("ref", "")
        if ref != "refs/heads/main":
            log(f"SKIPPED: Push to {ref}, not main")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Not main branch, skipping")
            return

        log(f"DEPLOYING: Push to main by {data.get('pusher', {}).get('name', 'unknown')}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Deploy triggered")

        # Run deploy in background so we don't block the response
        subprocess.Popen(
            ["bash", DEPLOY_SCRIPT],
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
        )

    def log_message(self, format, *args):
        # Suppress default access logging
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 9000), WebhookHandler)
    log("Webhook listener started on 127.0.0.1:9000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
        server.server_close()
