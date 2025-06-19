import threading
import urllib.parse
import urllib.request
import requests

from PyQt5.QtCore import QObject, pyqtSignal

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

from database import DatabaseManager
from http.server import HTTPServer, BaseHTTPRequestHandler

class RequestTokenServer(QObject):
    token_received = pyqtSignal(str)
    server_error = pyqtSignal(str)

    def __init__(self, kite_instance, db_path: str):
        super().__init__()
        self.kite = kite_instance
        self.db_path = db_path
        self._server = None
        self._server_thread = None
        self._running = False
        self._db_manager_thread_safe = None

    def run(self):
        self._db_manager_thread_safe = DatabaseManager(db_path=self.db_path)
        self._running = True
        try:
            class CallbackHandler(BaseHTTPRequestHandler):
                _parent_server = self

                def do_GET(self):
                    if self.path.startswith("/?"):
                        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        request_token = query_params.get('request_token', [None])[0]

                        if request_token:
                            try:
                                api_secret = self._parent_server._db_manager_thread_safe.get_setting("api_secret")
                                if not api_secret:
                                    raise ValueError("API Secret not found in database. Cannot generate session.")

                                data = self._parent_server.kite.generate_session(request_token, api_secret=api_secret)
                                access_token = data["access_token"]
                                self.send_response(200)
                                self.send_header('Content-type', 'text/html')
                                self.end_headers()
                                self.wfile.write(b"<html><body><h1>Access Token Received!</h1><p>You can close this window.</p></body></html>")
                                self._parent_server.token_received.emit(access_token)
                            except Exception as e:
                                self.send_response(500)
                                self.send_header('Content-type', 'text/html')
                                self.end_headers()
                                self.wfile.write(f"<html><body><h1>Error</h1><p>Failed to get access token: {e}</p></body></html>".encode())
                                self._parent_server.server_error.emit(f"Failed to generate session: {e}")
                        else:
                            self.send_response(400)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b"<html><body><h1>Error</h1><p>No request token found in callback.</p></body></html>")
                            self._parent_server.server_error.emit("No request token found in callback.")
                    else:
                        self.send_response(404)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        self.wfile.write(b"<html><body><h1>404 Not Found</h1></body></html>")

                def log_message(self, format, *args):
                    return

            self._server = HTTPServer(("localhost", 5000), CallbackHandler)
            self._server.serve_forever()

        except Exception as e:
            self.server_error.emit(f"HTTP server failed to start: {str(e)}")

    def start(self):
        if not self._running:
            self._server_thread = threading.Thread(target=self.run)
            self._server_thread.daemon = True # Allow main program to exit even if thread is running
            self._server_thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._running = False
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1) # Wait for thread to finish

def send_telegram_message(bot_token: str, chat_id: str, message: str):
    if not bot_token or not chat_id:
        print("[Telegram] Missing bot_token or chat_id.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': "HTML"
    }

    try:
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
        print("[Telegram] Message sent.")
    except Exception as e:
        print(f"[Telegram] Requests failed: {e}. Falling back to urllib.")
        try:
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                print(f"[Telegram] Sent via urllib. Status: {resp.status}")
        except Exception as e2:
            print(f"[Telegram] Urllib failed: {e2}")