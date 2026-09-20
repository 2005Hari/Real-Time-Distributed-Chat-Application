from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional
import json
import logging
import asyncio
import os
import re
import uuid
import aiofiles
from datetime import datetime, timezone

from server.sql_service import SQLService

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="QuantumConnect Hub", version="2.1.0")

# Directories (set DATA_DIR to a persistent disk path, e.g. /var/data on Render)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv('DATA_DIR', BASE_DIR)
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Limits
MAX_MESSAGE_LEN = 4000
MAX_USERNAME_LEN = 24
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# The frontend lives on another origin (Vercel), so list it in ALLOWED_ORIGINS as a
# comma-separated list, e.g. "https://my-chat.vercel.app". Defaults to allow-all.
ALLOWED_ORIGINS = [o.strip().rstrip('/') for o in os.getenv('ALLOWED_ORIGINS', '*').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database
db = SQLService(os.path.join(DATA_DIR, 'chatroom.db'))

# --- MODELS ---
class UserProfile(BaseModel):
    user_id: str
    username: str

# --- HELPERS ---
def now_iso() -> str:
    """Current time as an ISO-8601 UTC string (the client converts to local time)."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def to_iso(ts: Optional[str]) -> Optional[str]:
    """SQLite CURRENT_TIMESTAMP is UTC 'YYYY-MM-DD HH:MM:SS'; make it explicit ISO-8601 UTC."""
    if not ts:
        return None
    return ts if 'T' in ts else ts.replace(' ', 'T') + 'Z'

def format_message(row: dict) -> dict:
    return {
        "sender": row['sender_name'],
        "sender_id": row['sender_id'],
        "content": row['content'],
        "timestamp": to_iso(row['timestamp'])
    }

def clean_username(raw) -> str:
    return " ".join(str(raw or "").split())[:MAX_USERNAME_LEN] or "Guest"

# --- CONNECTION MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_profiles: Dict[str, str] = {}  # user_id -> username

    async def connect(self, websocket: WebSocket, user_id: str, username: str):
        # Same account opened elsewhere (second tab, or a dead socket after a network drop):
        # the newest connection wins and the old one is told why it was closed.
        old = self.active_connections.get(user_id)
        if old is not None and old is not websocket:
            try:
                await old.send_json({"type": "replaced"})
                await old.close(code=4001)
            except Exception:
                pass

        self.active_connections[user_id] = websocket
        self.user_profiles[user_id] = username
        db.update_user_status(user_id, True)

        history = [format_message(h) for h in reversed(db.get_public_messages(limit=50))]
        chats = [{
            "chat_id": c['chat_id'],
            "other_user": c['other_user'],
            "other_user_id": c['other_user_id'],
            "last_message": c['last_message'],
            "last_message_time": to_iso(c['last_message_time'])
        } for c in db.get_user_chats(user_id)]

        await websocket.send_json({
            "type": "welcome",
            "user_id": user_id,
            "username": username,
            "history": history,
            "chats": chats
        })
        await self.broadcast_user_list()

    def disconnect(self, user_id: str, websocket: WebSocket) -> bool:
        """Remove the connection unless it was already replaced by a newer one."""
        if self.active_connections.get(user_id) is not websocket:
            return False
        del self.active_connections[user_id]
        self.user_profiles.pop(user_id, None)
        db.update_user_status(user_id, False)
        return True

    async def send_to(self, user_id: str, message: dict):
        connection = self.active_connections.get(user_id)
        if connection is None:
            return
        try:
            await connection.send_json(message)
        except Exception as e:
            # Ghost connection; its own handler cleans up when the socket closes
            logger.warning("Failed to send to %s: %r", user_id, e)

    async def broadcast(self, message: dict, exclude: Optional[str] = None):
        targets = [uid for uid in list(self.active_connections) if uid != exclude]
        await asyncio.gather(*(self.send_to(uid, message) for uid in targets))

    async def broadcast_user_list(self):
        users = [{"user_id": uid, "username": name} for uid, name in self.user_profiles.items()]
        await self.broadcast({
            "type": "user_list",
            "users": users
        })

    async def handle_public_message(self, sender_id: str, message: dict):
        content = str(message.get('content') or '').strip()[:MAX_MESSAGE_LEN]
        if not content:
            return

        db.post_public_message(sender_id, content)
        await self.broadcast({
            "type": "public_message",
            "sender": self.user_profiles.get(sender_id, "Unknown"),
            "sender_id": sender_id,
            "content": content,
            "timestamp": now_iso()
        })

    async def handle_private_message(self, sender_id: str, message: dict):
        chat_id = message.get('chat_id')
        content = str(message.get('content') or '').strip()[:MAX_MESSAGE_LEN]

        if not chat_id or not content:
            return

        participants = db.get_chat_participants(chat_id)
        if not participants or sender_id not in participants:
            return

        if not db.post_private_message(chat_id, sender_id, content):
            return

        recipient_id = participants[0] if participants[1] == sender_id else participants[1]
        recipient = db.get_user(recipient_id)
        payload = {
            "type": "private_message",
            "chat_id": chat_id,
            "sender": self.user_profiles.get(sender_id, "Unknown"),
            "sender_id": sender_id,
            "recipient": recipient['username'] if recipient else "",
            "recipient_id": recipient_id,
            "content": content,
            "timestamp": now_iso()
        }
        # Echo to the sender as well so every device/tab shows the same thread
        await self.send_to(sender_id, payload)
        await self.send_to(recipient_id, payload)

    async def handle_private_request(self, sender_id: str, message: dict):
        recipient_username = clean_username(message.get('recipient'))
        recipient = db.get_user_by_username(recipient_username)
        if not recipient or recipient['user_id'] == sender_id:
            return

        chat_id = db.get_or_create_private_chat(sender_id, recipient['user_id'])
        if not chat_id:
            await self.send_to(sender_id, {"type": "error", "message": "Could not open that conversation."})
            return

        history = [format_message(m) for m in reversed(db.get_private_messages(chat_id, limit=100))]
        # Only the requester is switched into the chat; the other person just sees
        # an unread conversation appear when the first message arrives.
        await self.send_to(sender_id, {
            "type": "private_chat_start",
            "chat_id": chat_id,
            "other_user": recipient['username'],
            "other_user_id": recipient['user_id'],
            "history": history,
            "timestamp": now_iso()
        })

    async def handle_typing(self, sender_id: str, message: dict):
        scope = message.get('scope')
        payload = {
            "type": "typing",
            "scope": scope,
            "sender": self.user_profiles.get(sender_id, "Unknown"),
            "sender_id": sender_id
        }
        if scope == 'public':
            await self.broadcast(payload, exclude=sender_id)
            return

        participants = db.get_chat_participants(scope) if isinstance(scope, str) else None
        if participants and sender_id in participants:
            other_id = participants[0] if participants[1] == sender_id else participants[1]
            await self.send_to(other_id, payload)

manager = ConnectionManager()

# --- FILE ENDPOINTS ---

@app.post("/upload")
async def upload_file(filename: str, file: UploadFile = File(...)):
    ext = re.sub(r'[^A-Za-z0-9.]', '', os.path.splitext(filename)[1])[:10]
    unique_name = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    async with aiofiles.open(filepath, 'wb') as out_file:
        await out_file.write(content)

    return {"url": f"uploads/{unique_name}", "name": filename}

# --- REST API ---

@app.get("/")
async def root():
    return {"service": "QuantumConnect Hub", "status": "ok", "docs": "/docs"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "nodes": len(manager.active_connections)}

@app.get("/api/history")
async def get_history(limit: int = 50):
    return db.get_public_messages(limit=limit)

# --- WEBSOCKET ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    user_id = None
    try:
        data = await websocket.receive_text()
        reg_data = json.loads(data)

        if not isinstance(reg_data, dict) or reg_data.get("type") != "register":
            await websocket.close(code=4000)
            return

        username = clean_username(reg_data.get("username"))

        # Ensure user exists in Database to prevent Foreign Key crashes
        user_record = db.get_user_by_username(username)
        if user_record:
            user_id = user_record['user_id']
        else:
            user_id = str(uuid.uuid4())
            db.create_user(user_id, username)

        await manager.connect(websocket, user_id, username)

        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(message_data, dict):
                continue

            try:
                message_type = message_data.get("type")
                if message_type == "public_message":
                    await manager.handle_public_message(user_id, message_data)
                elif message_type == "private_message":
                    await manager.handle_private_message(user_id, message_data)
                elif message_type == "private_request":
                    await manager.handle_private_request(user_id, message_data)
                elif message_type == "typing":
                    await manager.handle_typing(user_id, message_data)
                elif message_type == "ping":
                    await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                raise
            except Exception:
                # One bad message must not drop the connection
                logger.exception("Error handling %s message", message_data.get("type"))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if user_id and manager.disconnect(user_id, websocket):
            await manager.broadcast_user_list()

# Uploaded files are served by the backend; the UI itself is hosted separately (Vercel)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print("\n" + "="*50)
    print("  QUANTUMCONNECT ENTERPRISE HUB STARTED")
    print(f"  API + WebSocket at:   http://localhost:{port}")
    print(f"  API Documentation at: http://localhost:{port}/docs")
    print("  UI is served separately from ../frontend")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
