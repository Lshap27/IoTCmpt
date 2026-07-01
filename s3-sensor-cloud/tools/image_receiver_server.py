from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from pathlib import Path

SAVE_DIR = Path("captures")
SAVE_DIR.mkdir(exist_ok=True)


class UploadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_response(self, status_code: int, body: bytes):
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_POST(self):
        if self.path != "/upload":
            self._send_response(404, b"Not Found")
            return

        content_length = int(self.headers.get("Content-Length", 0))

        if content_length <= 0:
            self._send_response(400, b"No image data")
            return

        image_data = self.rfile.read(content_length)

        filename = datetime.now().strftime("capture_%Y%m%d_%H%M%S.jpg")
        filepath = SAVE_DIR / filename

        with open(filepath, "wb") as f:
            f.write(image_data)

        print(f"Saved {filepath}, size={len(image_data)} bytes")

        self._send_response(200, b"OK")


def main():
    host = "0.0.0.0"
    port = 8000

    server = HTTPServer((host, port), UploadHandler)
    print(f"Listening on http://{host}:{port}")
    print("Upload endpoint: /upload")
    server.serve_forever()


if __name__ == "__main__":
    main()