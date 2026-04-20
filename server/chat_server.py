from sql_service import SQLService
import asyncio
import websockets 
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Set, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatServer:
    def __init__(self, host='0.0.0.0', port=8888):
        self.host = host
        self.port = port
        self.db = SQLService()
        self.active_connections: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.usernames: Dict[str, str] = {}  # user_id: username

    async def handle_connection(self, websocket, path=None):
        """Handle new WebSocket connection"""
        try:
            # First message must be username
            message = await websocket.recv()
            data = json.loads(message)
            
            if data.get('type') != 'register':
                await websocket.close(code=1008, reason="First message must be registration")
                return

            username = data.get('username', '').strip()
            if not username:
                await websocket.close(code=1008, reason="Username required")
                return

            # Check if username is already connected
            if username in self.usernames.values():
                await websocket.close(code=1008, reason="Username already in use")
                return

            # Create or get user
            user = self.db.get_user_by_username(username)
            if user:
                user_id = user['user_id']
            else:
                user_id = str(uuid.uuid4())
                success, msg = self.db.create_user(user_id, username)
                if not success:
                    await websocket.close(code=1008, reason=msg)
                    return

            # Register connection
            self.active_connections[user_id] = websocket
            self.usernames[user_id] = username
            self.db.update_user_status(user_id, True)
            
            # Send welcome message
            await websocket.send(json.dumps({
                "type": "welcome",
                "user_id": user_id,
                "username": username,
                "message": f"Welcome {username}!"
            }))

            # Send updated user list to all clients
            await self.broadcast_user_list()

            # Main message loop
            async for message in websocket:
                await self.handle_message(user_id, message)

        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
        finally:
            if 'user_id' in locals():
                await self.cleanup_connection(user_id)

    async def handle_message(self, user_id, raw_message):
        try:
            message = json.loads(raw_message)
            msg_type = message.get('type')
            
            if msg_type == 'public_message':
                content = message.get('content', '').strip()
                if content:
                    message_id = self.db.post_public_message(user_id, content)
                    if message_id:
                        await self.broadcast({
                            "type": "public_message",
                            "sender": self.usernames[user_id],
                            "sender_id": user_id,
                            "content": content,
                            "timestamp": datetime.now().isoformat()
                        }, exclude=[user_id])

            elif msg_type == 'private_message':
                await self.handle_private_message(user_id, message)
                
            elif msg_type == 'private_request':
                await self.handle_private_request(user_id, message)

        except json.JSONDecodeError:
            logger.error("Invalid message format")

    async def handle_private_message(self, sender_id, message):
        chat_id = message.get('chat_id')
        content = message.get('content', '').strip()
        
        if not chat_id or not content:
            return
            
        participants = self.db.get_chat_participants(chat_id)
        if not participants or sender_id not in participants:
            return

        message_id = self.db.post_private_message(chat_id, sender_id, content)
        if message_id:
            recipient_id = participants[0] if participants[1] == sender_id else participants[1]
            if recipient_id in self.active_connections:
                await self.active_connections[recipient_id].send(json.dumps({
                    "type": "private_message",
                    "chat_id": chat_id,
                    "sender": self.usernames[sender_id],
                    "sender_id": sender_id,
                    "content": content,
                    "timestamp": datetime.now().isoformat()
                }))

    async def handle_private_request(self, sender_id, message):
        recipient_username = message.get('recipient', '').strip()
        if not recipient_username:
            return
            
        recipient_id = next((uid for uid, name in self.usernames.items() if name == recipient_username), None)
        if not recipient_id or recipient_id == sender_id:
            return

        chat_id = self.db.get_or_create_private_chat(sender_id, recipient_id)
        if chat_id:
            # Notify both users
            for user_id in [sender_id, recipient_id]:
                if user_id in self.active_connections:
                    other_user = self.usernames[recipient_id] if user_id == sender_id else self.usernames[sender_id]
                    await self.active_connections[user_id].send(json.dumps({
                        "type": "private_chat_start",
                        "chat_id": chat_id,
                        "other_user": other_user,
                        "other_user_id": recipient_id if user_id == sender_id else sender_id,
                        "timestamp": datetime.now().isoformat()
                    }))

    async def cleanup_connection(self, user_id):
        """Clean up disconnected users"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.usernames:
            del self.usernames[user_id]
        self.db.update_user_status(user_id, False)
        await self.broadcast_user_list()

    async def broadcast(self, message, exclude=None):
        """Broadcast message to all connected clients"""
        exclude = exclude or []
        for uid, ws in self.active_connections.items():
            if uid not in exclude:
                try:
                    await ws.send(json.dumps(message))
                except:
                    await self.cleanup_connection(uid)

    async def broadcast_user_list(self):
        """Send updated user list to all clients"""
        users = [{"user_id": uid, "username": name} for uid, name in self.usernames.items()]
        await self.broadcast({
            "type": "user_list",
            "users": users
        })

    async def start(self):
        """Start the WebSocket server"""
        async with websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10
        ):
            import socket
            lan_ip = socket.gethostbyname(socket.gethostname())
            logger.info(f"Server started! Listening on all interfaces (port {self.port})")
            logger.info(f"Friends on your network should connect to: ws://{lan_ip}:{self.port}")
            await asyncio.Future()  # Run forever

if __name__ == "__main__":
    server = ChatServer()
    asyncio.run(server.start())