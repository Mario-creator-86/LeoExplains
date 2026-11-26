"""Serve prompts_all.json to the Flow page: python serve.py [port]  (default 8793)."""
import http.server, pathlib, sys
D = pathlib.Path(__file__).parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8793


class H(http.server.BaseHTTPRequestHandler):
    def _h(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._h(); self.end_headers()

    def do_GET(self):
        # /v/NN -> prompts_vertical_NN.json (private per-episode copy), anything else -> prompts_all.json
        parts = self.path.strip("/").split("/")
        f = f"prompts_vertical_{int(parts[1])}.json" if len(parts) == 2 and parts[0] == "v" else "prompts_all.json"
        if not (D / f).exists():
            self.send_response(404); self._h(); self.end_headers(); return
        b = (D / f).read_bytes()
        self.send_response(200); self._h()
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a): pass


http.server.HTTPServer(("127.0.0.1", PORT), H).serve_forever()
