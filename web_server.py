"""
Simple HTTP server that serves the web chat client.
Now supports /upload for files, images, and voice notes!
"""
import http.server
import socketserver
import os
import uuid
import json
import urllib.parse

PORT = 5000
WEB_DIR = os.path.join(os.path.dirname(__file__), 'web_client')
UPLOAD_DIR = os.path.join(WEB_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)
        # Ensure browsers recognize voice notes and images properly
        self.extensions_map.update({
            '.webm': 'audio/webm',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.mp4': 'video/mp4',
        })
        
    def log_message(self, format, *args):
        # Keep logs clean
        pass
        
    def address_string(self):
        # Fixes slow DNS lookups on local networks
        return self.client_address[0]
        
    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/upload':
            try:
                length = int(self.headers.get('content-length', 0))
                file_data = self.rfile.read(length)
                
                query = urllib.parse.parse_qs(parsed_path.query)
                filename = query.get('filename', ['upload.bin'])[0]
                ext = os.path.splitext(filename)[1]
                
                # Prevent malicious extensions if necessary, but for LAN it's fine
                unique_name = str(uuid.uuid4()) + ext
                filepath = os.path.join(UPLOAD_DIR, unique_name)
                
                with open(filepath, 'wb') as f:
                    f.write(file_data)
                    
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = {"url": f"uploads/{unique_name}", "name": filename}
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                print("Upload error:", e)
        else:
            self.send_response(404)
            self.end_headers()

def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except:
        return "localhost"
    finally:
        s.close()

if __name__ == "__main__":
    ip = get_local_ip()
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 50)
        print(f"  WEB CHAT SERVER RUNNING FOR LAN!")
        print(f"  (Supports File & Voice Sharing)")
        print(f"  Share this link with friends:")
        print(f"  --> http://{ip}:{PORT}")
        print("=" * 50)
        httpd.serve_forever()
