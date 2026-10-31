import http.server, os, socket

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello from {socket.gethostname()} ({os.environ.get('NODE_NAME', '-')})\n".encode()
        self.send_response(200); self.send_header("Content-Type", "text/plain")
        self.end_headers(); self.wfile.write(body)

http.server.HTTPServer(("", 8080), H).serve_forever()
