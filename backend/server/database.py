import sqlite3
import os
from pathlib import Path

def init_db(db_path: str = None):
    """Initialize the SQLite database with required tables"""
    db_path = db_path or Path(__file__).parent.parent / 'chatroom.db'
    
    # Create database directory if it doesn't exist
    os.makedirs(db_path.parent, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables with proper SQL comments (-- instead of #)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        online BOOLEAN NOT NULL DEFAULT 0,
        last_seen TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS public_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(user_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS private_chats (
        chat_id TEXT PRIMARY KEY,
        user1_id TEXT NOT NULL,
        user2_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user1_id) REFERENCES users(user_id),
        FOREIGN KEY (user2_id) REFERENCES users(user_id),
        CHECK (user1_id < user2_id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS private_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (chat_id) REFERENCES private_chats(chat_id),
        FOREIGN KEY (sender_id) REFERENCES users(user_id)
    )
    ''')
    
    # Create indexes
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_public_messages_timestamp 
    ON public_messages(timestamp)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_private_messages_chat 
    ON private_messages(chat_id)
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_private_messages_timestamp 
    ON private_messages(timestamp)
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {db_path}")

if __name__ == "__main__":
    init_db()
    