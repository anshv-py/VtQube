import os
import threading
import time
import urllib.parse
import webbrowser
import requests
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal # Import QObject and pyqtSignal

# Assuming KiteConnect is available in the environment
try:
    from kiteconnect import KiteConnect
except ImportError:
    # Removed print statement
    KiteConnect = None # Set to None if not available

# Assuming DatabaseManager is available
from database import DatabaseManager
from http.server import HTTPServer, BaseHTTPRequestHandler # Moved import here to avoid circular dependency issues

class RequestTokenServer(QObject): # Inherit from QObject to use signals
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
        """Starts the HTTP server."""
        self._db_manager_thread_safe = DatabaseManager(db_path=self.db_path)
        self._running = True
        try:
            # Define a handler for the HTTP server
            class CallbackHandler(BaseHTTPRequestHandler):
                _parent_server = self # Reference to the outer RequestTokenServer instance

                def do_GET(self):
                    if self.path.startswith("/?"):
                        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        request_token = query_params.get('request_token', [None])[0]

                        if request_token:
                            try:
                                # Exchange request token for access token
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

                # Suppress logging to console
                def log_message(self, format, *args):
                    return

            self._server = HTTPServer(("localhost", 5000), CallbackHandler)
            # Removed print statement
            # Serve requests until stopped
            self._server.serve_forever()

        except Exception as e:
            self.server_error.emit(f"HTTP server failed to start: {str(e)}")
            # Removed print statement

    def start(self):
        """Starts the HTTP server in a new thread."""
        if not self._running:
            self._server_thread = threading.Thread(target=self.run)
            self._server_thread.daemon = True # Allow main program to exit even if thread is running
            self._server_thread.start()
            # Removed print statement

    def stop(self):
        """Stops the HTTP server."""
        if self._server:
            # Removed print statement
            self._server.shutdown()
            self._server.server_close()
            self._running = False
            # Removed print statement
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1) # Wait for thread to finish
            # Removed print statement

def send_telegram_message(bot_token: str, chat_id: str, message: str):
    """Sends a message via Telegram Bot API."""
    if not bot_token or not chat_id:
        # Removed print statement
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML' # Use HTML for formatting if needed
    }

    try:
        if requests:
            response = requests.post(url, data=payload)
            response.raise_for_status() # Raise an exception for HTTP errors
            # Removed print statement
        else:
            # Fallback to urllib if requests is not installed
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req) as response:
                response_data = response.read().decode('utf-8')
                # Removed print statement
                # print(f"Response: {response_data}") # Uncomment for debugging urllib response
    except Exception as e:
        # Removed print statement
        pass