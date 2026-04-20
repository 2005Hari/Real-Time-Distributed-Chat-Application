import unittest
import sqlite3
import os
from server.database import init_db
from server.sql_service import SQLService

class TestDatabase(unittest.TestCase):
    TEST_DB = 'test_chatroom.db'

    def setUp(self):
        # Setup test database
        if os.path.exists(self.TEST_DB):
            os.remove(self.TEST_DB)
        
        self.conn = sqlite3.connect(self.TEST_DB)
        init_db(self.conn)
        self.db = SQLService(self.TEST_DB)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.TEST_DB):
            os.remove(self.TEST_DB)

    def test_user_management(self):
        """Test user creation and status updates"""
        # Create user
        self.db.create_user('user1', 'testuser')
        
        # Verify user exists
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT username FROM users WHERE user_id = 'user1'")
            result = cur.fetchone()
            self.assertEqual(result[0], 'testuser')
        
        # Update status
        self.db.update_user_status('user1', True)
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT online FROM users WHERE user_id = 'user1'")
            self.assertTrue(cur.fetchone()[0])

    def test_message_storage(self):
        """Test public/private message storage"""
        # Setup users
        self.db.create_user('user1', 'alice')
        self.db.create_user('user2', 'bob')
        
        # Test public message
        msg_id = self.db.post_public_message('user1', 'Hello public')
        self.assertIsNotNone(msg_id)
        
        # Test private message
        chat_id = self.db.create_private_chat('user1', 'user2')
        msg_id = self.db.post_private_message(chat_id, 'user1', 'Hello private')
        self.assertIsNotNone(msg_id)
        
        # Verify retrieval
        public_msgs = self.db.get_public_messages()
        self.assertEqual(len(public_msgs), 1)
        
        private_msgs = self.db.get_private_messages(chat_id)
        self.assertEqual(len(private_msgs), 1)

if __name__ == '__main__':
    unittest.main()