"""
Local development server for the Fitbit Healthspan / Biological Age Dashboard.
Runs on http://localhost:8765 with zero external dependencies.
"""

from http.server import ThreadingHTTPServer
from server_handler import HealthspanHandler

PORT = 8765


class LocalHandler(HealthspanHandler):
    serve_static = True


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), LocalHandler)
    print(f"Healthspan Dashboard running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
