# server/private_chat_handler.py
from typing import Dict, Set
from websockets import WebSocketServerProtocol
from .sql_service import SQLService
import json
import logging

class PrivateChatHandler:
    def __init__(self, sql_service: SQLService):
        self.sql_service = sql_service
        self.active_connections: Dict[int, WebSocketServerProtocol] = {}
        self.user_chats: Dict[int, Set[int]] = {}  # user_id: set of chat_ids
        self.logger = logging.getLogger(__name__)

    async def register_user(self, user_id: int, websocket: WebSocketServerProtocol):
        """Register a user's WebSocket connection"""
        self.active_connections[user_id] = websocket
        self.logger.info(f"User {user_id} registered for private messaging")

    async def unregister_user(self, user_id: int):
        """Unregister a user's WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            self.logger.info(f"User {user_id} unregistered from private messaging")

    async def handle_private_message(self, websocket: WebSocketServerProtocol, message_data: dict):
        """Handle incoming private messages and broadcast to recipient"""
        try:
            sender_id = message_data['sender_id']
            recipient_id = message_data['recipient_id']
            content = message_data['content']

            # Get or create chat between users
            chat_id = self.sql_service.get_or_create_private_chat(sender_id, recipient_id)
            if not chat_id:
                self.logger.error(f"Failed to get/create chat between {sender_id} and {recipient_id}")
                return {'type': 'private_message', 'success': False}

            # Store message in database
            message_id = self.sql_service.post_private_message(chat_id, sender_id, content)
            if not message_id:
                self.logger.error(f"Failed to store message in chat {chat_id}")
                return {'type': 'private_message', 'success': False}

            # Prepare message for broadcasting
            message = {
                'type': 'private_message',
                'chat_id': chat_id,
                'sender_id': sender_id,
                'recipient_id': recipient_id,
                'content': content,
                'timestamp': message_data.get('timestamp'),
                'message_id': message_id
            }

            # Send to sender (for their own UI update)
            if sender_id in self.active_connections:
                await self.active_connections[sender_id].send(json.dumps(message))

            # Send to recipient if online
            if recipient_id in self.active_connections:
                await self.active_connections[recipient_id].send(json.dumps(message))
                self.logger.debug(f"Message delivered to recipient {recipient_id}")
            else:
                self.logger.info(f"Recipient {recipient_id} is offline. Message stored in database.")

            return {'type': 'private_message', 'success': True, 'message_id': message_id}

        except Exception as e:
            self.logger.error(f"Error handling private message: {str(e)}")
            return {'type': 'private_message', 'success': False, 'error': str(e)}

    async def get_chat_history(self, chat_id: int, user_id: int):
        """Retrieve chat history for a private chat with participant validation"""
        try:
            participants = self.sql_service.get_chat_participants(chat_id)
            if not participants or user_id not in participants:
                self.logger.warning(f"User {user_id} not authorized for chat {chat_id}")
                return None

            history = self.sql_service.get_private_chat_history(chat_id)
            return {
                'type': 'chat_history',
                'chat_id': chat_id,
                'history': history,
                'participants': participants
            }
        except Exception as e:
            self.logger.error(f"Error getting chat history: {str(e)}")
            return None

    async def get_user_chats(self, user_id: int):
        """Get all private chats for a user"""
        try:
            chats = self.sql_service.get_user_private_chats(user_id)
            return {
                'type': 'user_chats',
                'chats': chats
            }
        except Exception as e:
            self.logger.error(f"Error getting user chats: {str(e)}")
            return None