import unittest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from client.chat_client import ChatClient
from client.client_ui import ChatClientUI

class TestChatClient(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
    def tearDown(self):
        self.loop.close()

    @patch('websockets.connect', new_callable=AsyncMock)
    async def test_client_connection(self, mock_connect):
        """Test client connection to server"""
        mock_ws = AsyncMock()
        mock_connect.return_value = mock_ws
        
        client = ChatClient()
        await client.connect()
        
        mock_connect.assert_awaited_with('ws://localhost:8888')
        self.assertTrue(client.connected)

    @patch('websockets.connect', new_callable=AsyncMock)
    async def test_message_handling(self, mock_connect):
        """Test client message processing"""
        mock_ws = AsyncMock()
        mock_connect.return_value = mock_ws
        
        # Setup mock server responses
        async def mock_recv():
            return json.dumps({
                'type': 'public_message',
                'sender': 'testuser',
                'content': 'Hello world'
            })
        mock_ws.recv = mock_recv
        
        client = ChatClient()
        await client.connect()
        
        # Verify message handling
        with patch.object(client, 'handle_message') as mock_handler:
            await client.receive_messages()
            mock_handler.assert_called()

class TestChatClientUI(unittest.TestCase):
    def setUp(self):
        self.root = MagicMock()
        
    def test_ui_initialization(self):
        """Test UI components are created properly"""
        ui = ChatClientUI(self.root)
        
        # Verify main components exist
        self.assertIsNotNone(ui.chat_display)
        self.assertIsNotNone(ui.user_listbox)
        self.assertIsNotNone(ui.message_entry)
        
        # Verify initial state
        self.assertFalse(ui.connected)

    @patch('asyncio.run_coroutine_threadsafe')
    def test_connection(self, mock_run):
        """Test connection initiation"""
        ui = ChatClientUI(self.root)
        ui.connect_to_server()
        
        mock_run.assert_called()
        self.root.after.assert_called()

if __name__ == '__main__':
    unittest.main()