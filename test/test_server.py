import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from server.chat_server import ChatServer
from server.sql_service import SQLService

class TestChatServer(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.server = ChatServer()
        self.server.db = MagicMock(spec=SQLService)
        
        # Mock WebSocket connection
        self.websocket = AsyncMock()
        self.websocket.remote_address = ('127.0.0.1', 12345)
        self.websocket.send = AsyncMock()

    def tearDown(self):
        self.loop.close()

    async def test_handle_connection(self):
        """Test new client connection"""
        with patch('server.chat_server.uuid.uuid4', return_value='test-user-123'):
            await self.server.handle_connection(self.websocket, '/')
            
            # Verify user was registered
            self.server.db.create_user.assert_called_with('test-user-123', 'User12345')
            self.server.db.update_user_status.assert_called_with('test-user-123', True)
            
            # Verify welcome message sent
            self.websocket.send.assert_awaited()

    async def test_public_message(self):
        """Test public message handling"""
        # Setup test user
        self.server.active_connections = {'user1': self.websocket}
        self.server.db.get_user.return_value = {'username': 'testuser'}
        
        # Simulate message
        test_msg = json.dumps({
            'type': 'public_message',
            'content': 'Hello world'
        })
        await self.server.handle_message('user1', test_msg)
        
        # Verify DB call and broadcast
        self.server.db.post_public_message.assert_called_with('user1', 'Hello world')
        self.websocket.send.assert_awaited()

    async def test_private_chat_creation(self):
        """Test private chat initiation"""
        self.server.active_connections = {'user1': self.websocket, 'user2': AsyncMock()}
        
        # Simulate private chat request
        test_msg = json.dumps({
            'type': 'start_private_chat',
            'with_user': 'user2'
        })
        await self.server.handle_message('user1', test_msg)
        
        # Verify chat was created
        self.server.db.create_private_chat.assert_called_with('user1', 'user2')

if __name__ == '__main__':
    unittest.main()