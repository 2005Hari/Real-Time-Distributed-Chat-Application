import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class SQLService:
    def __init__(self, db_path: str = 'chatroom.db'):
        self.db_path = db_path
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Create and return a new database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dictionary-style access
        conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        return conn

    def _initialize_database(self):
        """Ensure all required tables exist with proper schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create tables if they don't exist
            cursor.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                online BOOLEAN NOT NULL DEFAULT 0,
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS public_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS private_chats (
                chat_id TEXT PRIMARY KEY,
                user1_id TEXT NOT NULL,
                user2_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user1_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (user2_id) REFERENCES users(user_id) ON DELETE CASCADE,
                CHECK (user1_id < user2_id)
            );

            CREATE TABLE IF NOT EXISTS private_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES private_chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            ''')
            
            # Create indexes
            cursor.executescript('''
            CREATE INDEX IF NOT EXISTS idx_public_messages_timestamp ON public_messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_private_messages_chat ON private_messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_private_messages_timestamp ON private_messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_private_chats_users ON private_chats(user1_id, user2_id);
            ''')
            
            conn.commit()

    # User operations
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Retrieve a user by ID including all fields"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users WHERE user_id = ?
            ''', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Retrieve a user by username"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users WHERE username = ?
            ''', (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_user(self, user_id: str, username: str) -> Tuple[bool, str]:
        """
        Create a new user
        Returns: (success: bool, message: str)
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    (user_id, username)
                )
                conn.commit()
                return True, "User created successfully"
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint" in str(e):
                return False, "Username already exists"
            return False, f"Database error: {str(e)}"
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            return False, f"Unexpected error: {str(e)}"

    def update_user_status(self, user_id: str, online: bool) -> bool:
        """Update user's online status and last seen timestamp"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET online = ?, 
                    last_seen = CASE WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE user_id = ?
            ''', (online, online, user_id))
            conn.commit()
            return cursor.rowcount > 0

    # Public message operations
    def post_public_message(self, sender_id: str, content: str) -> Optional[int]:
        """Store a public message and return its ID"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO public_messages (sender_id, content)
                    VALUES (?, ?)
                    RETURNING message_id
                ''', (sender_id, content))
                result = cursor.fetchone()
                conn.commit()
                return result['message_id'] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error posting public message: {str(e)}")
            return None

    def get_public_messages(self, limit: int = 100) -> List[Dict]:
        """Retrieve recent public messages with sender info"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, u.username as sender_name 
                FROM public_messages m
                JOIN users u ON m.sender_id = u.user_id
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # Private chat operations
    def create_private_chat(self, user1_id: str, user2_id: str) -> Optional[str]:
        """Create a private chat between two users"""
        user1_id, user2_id = sorted([user1_id, user2_id])
        chat_id = f"{user1_id}_{user2_id}"
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO private_chats 
                    (chat_id, user1_id, user2_id) 
                    VALUES (?, ?, ?)
                ''', (chat_id, user1_id, user2_id))
                conn.commit()
                return chat_id
        except sqlite3.Error as e:
            logger.error(f"Error creating private chat: {str(e)}")
            return None

    def get_chat_participants(self, chat_id: str) -> Optional[Tuple[str, str]]:
        """Get both participants in a private chat"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user1_id, user2_id FROM private_chats WHERE chat_id = ?
            ''', (chat_id,))
            result = cursor.fetchone()
            return (result['user1_id'], result['user2_id']) if result else None

    def get_or_create_private_chat(self, user1_id: str, user2_id: str) -> Optional[str]:
        """Get existing chat ID or create new one"""
        user1_id, user2_id = sorted([user1_id, user2_id])
        chat_id = f"{user1_id}_{user2_id}"
        
        with self._get_connection() as conn:
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO private_chats 
                    (chat_id, user1_id, user2_id) 
                    VALUES (?, ?, ?)
                ''', (chat_id, user1_id, user2_id))
                conn.commit()
                return chat_id
            except sqlite3.Error as e:
                logger.error(f"Error creating private chat: {str(e)}")
                return None

    def post_private_message(self, chat_id: str, sender_id: str, content: str) -> Optional[int]:
        """Store a private message and return its ID"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO private_messages (chat_id, sender_id, content)
                    VALUES (?, ?, ?)
                    RETURNING message_id
                ''', (chat_id, sender_id, content))
                result = cursor.fetchone()
                conn.commit()
                return result['message_id'] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error posting private message: {str(e)}")
            return None

    def get_private_chat_history(self, chat_id: str, limit: int = 100) -> List[Dict]:
        """Retrieve private chat history with sender info"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, u.username as sender_name 
                FROM private_messages m
                JOIN users u ON m.sender_id = u.user_id
                WHERE m.chat_id = ?
                ORDER BY m.timestamp ASC
                LIMIT ?
            ''', (chat_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_private_messages(self, chat_id: str, limit: int = 100) -> List[Dict]:
        """Retrieve messages from a private chat (ordered newest first)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, u.username as sender_name 
                FROM private_messages m
                JOIN users u ON m.sender_id = u.user_id
                WHERE m.chat_id = ?
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (chat_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_user_chats(self, user_id: str) -> List[Dict]:
        """Get all private chats for a user with participant info"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT c.*, 
                       CASE WHEN c.user1_id = ? THEN u2.username ELSE u1.username END as other_user,
                       CASE WHEN c.user1_id = ? THEN u2.user_id ELSE u1.user_id END as other_user_id,
                       (SELECT content FROM private_messages 
                        WHERE chat_id = c.chat_id 
                        ORDER BY timestamp DESC LIMIT 1) as last_message,
                       (SELECT timestamp FROM private_messages 
                        WHERE chat_id = c.chat_id 
                        ORDER BY timestamp DESC LIMIT 1) as last_message_time
                FROM private_chats c
                JOIN users u1 ON c.user1_id = u1.user_id
                JOIN users u2 ON c.user2_id = u2.user_id
                WHERE c.user1_id = ? OR c.user2_id = ?
                ORDER BY last_message_time DESC
            ''', (user_id, user_id, user_id, user_id))
            return [dict(row) for row in cursor.fetchall()]

    def get_unread_message_count(self, user_id: str, chat_id: str, last_seen: str) -> int:
        """Get count of unread messages in a chat"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM private_messages
                WHERE chat_id = ? 
                AND sender_id != ?
                AND timestamp > ?
            ''', (chat_id, user_id, last_seen))
            result = cursor.fetchone()
            return result['count'] if result else 0

    # User list operations
    def get_online_users(self) -> List[Dict]:
        """Get all currently online users"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username 
                FROM users 
                WHERE online = 1
                ORDER BY username
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def search_users(self, query: str) -> List[Dict]:
        """Search users by username"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id, username, online
                FROM users
                WHERE username LIKE ?
                ORDER BY username
                LIMIT 20
            ''', (f'%{query}%',))
            return [dict(row) for row in cursor.fetchall()]