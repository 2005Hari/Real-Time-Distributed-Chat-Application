import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger(__name__)


def normalize_database_url(target: str) -> str:
    """Accept a plain SQLite file path or a database URL (Neon/Render style postgres:// URLs included)."""
    if '://' not in target:
        return f"sqlite:///{target}"
    for prefix in ('postgres://', 'postgresql://'):
        if target.startswith(prefix):
            return 'postgresql+psycopg2://' + target[len(prefix):]
    return target


class SQLService:
    """Chat persistence. Runs on SQLite (local development) or PostgreSQL (production)."""

    def __init__(self, db_path: str = 'chatroom.db'):
        self.db_path = db_path
        url = normalize_database_url(str(db_path))

        if url.startswith('sqlite'):
            self.engine = create_engine(
                url, connect_args={'check_same_thread': False, 'timeout': 30}, pool_pre_ping=True)

            @event.listens_for(self.engine, 'connect')
            def _enable_foreign_keys(dbapi_conn, _record):
                cursor = dbapi_conn.cursor()
                cursor.execute('PRAGMA foreign_keys = ON')
                cursor.close()
        else:
            # pool_pre_ping/recycle: hosted Postgres closes idle connections
            self.engine = create_engine(url, pool_size=5, max_overflow=5, pool_recycle=300, pool_pre_ping=True)

        self.is_postgres = self.engine.dialect.name == 'postgresql'
        self._initialize_database()

    # ---------- query helpers ----------
    def _all(self, sql: str, **params) -> List[Dict]:
        with self.engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(text(sql), params)]

    def _one(self, sql: str, **params) -> Optional[Dict]:
        rows = self._all(sql, **params)
        return rows[0] if rows else None

    def _write(self, sql: str, **params) -> int:
        with self.engine.begin() as conn:
            return conn.execute(text(sql), params).rowcount

    # ---------- schema ----------
    def _initialize_database(self):
        """Ensure all required tables exist with proper schema"""
        pg = self.is_postgres
        auto_id = 'BIGSERIAL PRIMARY KEY' if pg else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        created = 'TIMESTAMPTZ NOT NULL DEFAULT NOW()' if pg else 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
        moment = 'TIMESTAMPTZ' if pg else 'TIMESTAMP'
        no = 'FALSE' if pg else '0'

        statements = [
            f'''CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                online BOOLEAN NOT NULL DEFAULT {no},
                last_seen {moment},
                created_at {created}
            )''',
            f'''CREATE TABLE IF NOT EXISTS public_messages (
                message_id {auto_id},
                sender_id TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp {created},
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE
            )''',
            f'''CREATE TABLE IF NOT EXISTS private_chats (
                chat_id TEXT PRIMARY KEY,
                user1_id TEXT NOT NULL,
                user2_id TEXT NOT NULL,
                created_at {created},
                FOREIGN KEY (user1_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (user2_id) REFERENCES users(user_id) ON DELETE CASCADE,
                CHECK (user1_id < user2_id)
            )''',
            f'''CREATE TABLE IF NOT EXISTS private_messages (
                message_id {auto_id},
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp {created},
                FOREIGN KEY (chat_id) REFERENCES private_chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE CASCADE
            )''',
            'CREATE INDEX IF NOT EXISTS idx_public_messages_timestamp ON public_messages(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_private_messages_chat ON private_messages(chat_id)',
            'CREATE INDEX IF NOT EXISTS idx_private_messages_timestamp ON private_messages(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_private_chats_users ON private_chats(user1_id, user2_id)',
        ]
        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))

            # Databases created before accounts existed have no password column
            columns = {c['name'] for c in inspect(conn).get_columns('users')}
            if 'password_hash' not in columns:
                conn.execute(text('ALTER TABLE users ADD COLUMN password_hash TEXT'))

        # Usernames are unique regardless of case, so "Alice" cannot impersonate "alice"
        try:
            self._write('CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username_lower ON users (lower(username))')
        except SQLAlchemyError as e:
            logger.warning("Could not enforce case-insensitive usernames (existing duplicates?): %s", e)

    # ---------- users ----------
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Retrieve a user by ID including all fields"""
        return self._one('SELECT * FROM users WHERE user_id = :user_id', user_id=user_id)

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Retrieve a user by username (case-insensitive)"""
        return self._one('SELECT * FROM users WHERE lower(username) = lower(:username)', username=username)

    def create_user(self, user_id: str, username: str, password_hash: Optional[str] = None) -> Tuple[bool, str]:
        """
        Create a new user
        Returns: (success: bool, message: str)
        """
        try:
            self._write(
                'INSERT INTO users (user_id, username, password_hash) VALUES (:user_id, :username, :password_hash)',
                user_id=user_id, username=username, password_hash=password_hash)
            return True, "User created successfully"
        except IntegrityError as e:
            if 'unique' in str(e).lower():
                return False, "Username already exists"
            return False, f"Database error: {str(e)}"
        except SQLAlchemyError as e:
            logger.error(f"Error creating user: {str(e)}")
            return False, f"Unexpected error: {str(e)}"

    def update_user_status(self, user_id: str, online: bool) -> bool:
        """Update user's online status and last seen timestamp"""
        if online:
            sql = 'UPDATE users SET online = :online, last_seen = NULL WHERE user_id = :user_id'
        else:
            sql = 'UPDATE users SET online = :online, last_seen = CURRENT_TIMESTAMP WHERE user_id = :user_id'
        return self._write(sql, online=bool(online), user_id=user_id) > 0

    # ---------- public messages ----------
    def post_public_message(self, sender_id: str, content: str) -> Optional[int]:
        """Store a public message and return its ID"""
        try:
            with self.engine.begin() as conn:
                return conn.execute(text(
                    'INSERT INTO public_messages (sender_id, content) VALUES (:sender_id, :content) RETURNING message_id'),
                    {'sender_id': sender_id, 'content': content}).scalar()
        except SQLAlchemyError as e:
            logger.error(f"Error posting public message: {str(e)}")
            return None

    def get_public_messages(self, limit: int = 100) -> List[Dict]:
        """Retrieve recent public messages with sender info (newest first)"""
        return self._all('''
            SELECT m.*, u.username AS sender_name
            FROM public_messages m
            JOIN users u ON m.sender_id = u.user_id
            ORDER BY m.timestamp DESC, m.message_id DESC
            LIMIT :limit
        ''', limit=limit)

    # ---------- private chats ----------
    def create_private_chat(self, user1_id: str, user2_id: str) -> Optional[str]:
        """Create a private chat between two users"""
        user1_id, user2_id = sorted([user1_id, user2_id])
        chat_id = f"{user1_id}_{user2_id}"
        try:
            self._write('''
                INSERT INTO private_chats (chat_id, user1_id, user2_id)
                VALUES (:chat_id, :user1_id, :user2_id)
                ON CONFLICT (chat_id) DO NOTHING
            ''', chat_id=chat_id, user1_id=user1_id, user2_id=user2_id)
            return chat_id
        except SQLAlchemyError as e:
            logger.error(f"Error creating private chat: {str(e)}")
            return None

    def get_or_create_private_chat(self, user1_id: str, user2_id: str) -> Optional[str]:
        """Get existing chat ID or create new one"""
        return self.create_private_chat(user1_id, user2_id)

    def get_chat_participants(self, chat_id: str) -> Optional[Tuple[str, str]]:
        """Get both participants in a private chat"""
        row = self._one('SELECT user1_id, user2_id FROM private_chats WHERE chat_id = :chat_id', chat_id=chat_id)
        return (row['user1_id'], row['user2_id']) if row else None

    def post_private_message(self, chat_id: str, sender_id: str, content: str) -> Optional[int]:
        """Store a private message and return its ID"""
        try:
            with self.engine.begin() as conn:
                return conn.execute(text('''
                    INSERT INTO private_messages (chat_id, sender_id, content)
                    VALUES (:chat_id, :sender_id, :content)
                    RETURNING message_id
                '''), {'chat_id': chat_id, 'sender_id': sender_id, 'content': content}).scalar()
        except SQLAlchemyError as e:
            logger.error(f"Error posting private message: {str(e)}")
            return None

    def get_private_chat_history(self, chat_id: str, limit: int = 100) -> List[Dict]:
        """Retrieve private chat history with sender info (oldest first)"""
        return self._all('''
            SELECT m.*, u.username AS sender_name
            FROM private_messages m
            JOIN users u ON m.sender_id = u.user_id
            WHERE m.chat_id = :chat_id
            ORDER BY m.timestamp ASC, m.message_id ASC
            LIMIT :limit
        ''', chat_id=chat_id, limit=limit)

    def get_private_messages(self, chat_id: str, limit: int = 100) -> List[Dict]:
        """Retrieve messages from a private chat (ordered newest first)"""
        return self._all('''
            SELECT m.*, u.username AS sender_name
            FROM private_messages m
            JOIN users u ON m.sender_id = u.user_id
            WHERE m.chat_id = :chat_id
            ORDER BY m.timestamp DESC, m.message_id DESC
            LIMIT :limit
        ''', chat_id=chat_id, limit=limit)

    def get_user_chats(self, user_id: str) -> List[Dict]:
        """Get all private chats for a user with participant info"""
        return self._all('''
            SELECT c.*,
                   CASE WHEN c.user1_id = :user_id THEN u2.username ELSE u1.username END AS other_user,
                   CASE WHEN c.user1_id = :user_id THEN u2.user_id ELSE u1.user_id END AS other_user_id,
                   (SELECT content FROM private_messages
                    WHERE chat_id = c.chat_id
                    ORDER BY timestamp DESC, message_id DESC LIMIT 1) AS last_message,
                   (SELECT timestamp FROM private_messages
                    WHERE chat_id = c.chat_id
                    ORDER BY timestamp DESC, message_id DESC LIMIT 1) AS last_message_time
            FROM private_chats c
            JOIN users u1 ON c.user1_id = u1.user_id
            JOIN users u2 ON c.user2_id = u2.user_id
            WHERE c.user1_id = :user_id OR c.user2_id = :user_id
            ORDER BY last_message_time DESC NULLS LAST
        ''', user_id=user_id)

    def get_unread_message_count(self, user_id: str, chat_id: str, last_seen: str) -> int:
        """Get count of unread messages in a chat"""
        row = self._one('''
            SELECT COUNT(*) AS count
            FROM private_messages
            WHERE chat_id = :chat_id AND sender_id != :user_id AND timestamp > :last_seen
        ''', chat_id=chat_id, user_id=user_id, last_seen=last_seen)
        return row['count'] if row else 0

    # ---------- user lists ----------
    def get_online_users(self) -> List[Dict]:
        """Get all currently online users"""
        return self._all('SELECT user_id, username FROM users WHERE online = :online ORDER BY username', online=True)

    def search_users(self, query: str) -> List[Dict]:
        """Search users by username"""
        return self._all('''
            SELECT user_id, username, online
            FROM users
            WHERE lower(username) LIKE lower(:pattern)
            ORDER BY username
            LIMIT 20
        ''', pattern=f'%{query}%')
