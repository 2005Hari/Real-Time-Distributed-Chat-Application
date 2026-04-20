from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Set, Optional
import json
import logging
import asyncio
import os
import uuid
import shutil
import aiofiles
from datetime import datetime

from server.sql_service import SQLService

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="QuantumConnect Hub", version="2.0.0")

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, 'web_client')
UPLOAD_DIR = os.path.join(WEB_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Enable CORS for enterprise integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database
db = SQLService(os.path.join(BASE_DIR, 'chatroom.db'))

# --- MODELS ---
class UserProfile(BaseModel):
    user_id: str
    username: str

# --- CONNECTION MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_profiles: Dict[str, str] = {}  # user_id -> username

    async def connect(self, websocket: WebSocket, user_id: str, username: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_profiles[user_id] = username
        db.update_user_status(user_id, True)
        
        # Sync online users
        await self.broadcast_user_list()
        
        # Send history + welcome
        raw_history = db.get_public_messages(limit=50)
        # Format history for frontend
        history = []
        for h in reversed(raw_history):
            history.append({
                "sender": h['sender_name'],
                "sender_id": h['sender_id'],
                "content": h['content'],
                "timestamp": h['timestamp']
            })

        await websocket.send_json({
            "type": "welcome",
            "user_id": user_id,
            "username": username,
            "history": history
        })

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_profiles:
            del self.user_profiles[user_id]
        db.update_user_status(user_id, False)

    async def broadcast(self, message: dict):
        for uid, connection in self.active_connections.items():
            try:
                await connection.send_json(message)
            except:
                # Handle ghost connections
                pass

    async def broadcast_user_list(self):
        users = [{"user_id": uid, "username": name} for uid, name in self.user_profiles.items()]
        await self.broadcast({
            "type": "user_list",
            "users": users
        })

manager = ConnectionManager()

# --- WEB & FILE ENDPOINTS ---

@app.post("/upload")
async def upload_file(filename: str, file: UploadFile = File(...)):
    ext = os.path.splitext(filename)[1]
    unique_name = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)
    
    async with aiofiles.open(filepath, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)
        
    return {"url": f"uploads/{unique_name}", "name": filename}

# Serve the entire frontend (including index.html, JS, and uploads folder)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="static")

# --- REST API ---

@app.get("/health")
async def health_check():
    return {"status": "healthy", "nodes": len(manager.active_connections)}

@app.get("/api/history")
async def get_history(limit: int = 50):
    return db.get_public_messages(limit=limit)

# --- WEBSOCKET ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user_id = None
    try:
        data = await websocket.receive_text()
        reg_data = json.loads(data)
        
        if reg_data.get("type") != "register":
            await websocket.close(code=4000)
            return

        username = reg_data.get("username", "Internal User")
        user_id = reg_data.get("user_id", str(uuid.uuid4()))
        
        await manager.connect(websocket, user_id, username)

        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "public_message":
                content = message_data.get("content")
                if not content: continue
                
                # Save to DB
                db.post_public_message(user_id, content)
                
                # Broadcast to others
                await manager.broadcast({
                    "type": "public_message",
                    "sender": username,
                    "sender_id": user_id,
                    "content": content,
                    "timestamp": datetime.now().isoformat()
                })

    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(user_id)
            await manager.broadcast_user_list()
    except Exception as e:
        logger.error(f"Error: {e}")
        if user_id: manager.disconnect(user_id)

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("  QUANTUMCONNECT ENTERPRISE HUB STARTED")
    print("  Access the Dashboard at: http://localhost:8000")
    print("  API Documentation at:   http://localhost:8000/docs")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
