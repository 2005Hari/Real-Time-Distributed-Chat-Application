import os
from pathlib import Path
from typing import Dict, Any

# Base configuration
class Config:
    # Application metadata
    APP_NAME = "Distributed Chatroom"
    VERSION = "1.0.0"
    
    # Database configuration
    BASE_DIR = Path(__file__).parent.parent
    DATABASE = {
        'ENGINE': 'sqlite',
        'NAME': BASE_DIR / 'chatroom.db',
        'TEST_NAME': BASE_DIR / 'test_chatroom.db',
        'TIMEOUT': 30.0,  # SQLite busy timeout
        'PRAGMAS': {
            'journal_mode': 'WAL',  # Better concurrency
            'foreign_keys': 1,      # Enable FK constraints
            'ignore_check_constraints': 0
        }
    }
    
    # Server configuration
    SERVER = {
        'HOST': 'localhost',
        'PORT': 8888,
        'MAX_CONNECTIONS': 100,
        'MESSAGE_LIMIT': 1024 * 1024,  # 1MB max message size
        'PING_INTERVAL': 30,           # Seconds
        'PING_TIMEOUT': 10
    }
    
    # Client configuration
    CLIENT = {
        'RECONNECT_DELAY': 5,  # Seconds
        'MESSAGE_HISTORY': 100, # Number of messages to keep
        'UI_REFRESH_RATE': 1    # Seconds
    }
    
    # Security settings
    SECURITY = {
        'MAX_USERNAME_LENGTH': 20,
        'MESSAGE_RATE_LIMIT': 10,  # Messages per second
        'BAN_AFTER': 5             # Violations before ban
    }

    @classmethod
    def get_database_uri(cls, test: bool = False) -> str:
        """Get database connection URI"""
        db_name = cls.DATABASE['TEST_NAME'] if test else cls.DATABASE['NAME']
        return f"sqlite:///{db_name}?timeout={cls.DATABASE['TIMEOUT']}"

    @classmethod
    def get_pragmas(cls) -> Dict[str, Any]:
        """Get SQLite PRAGMA settings"""
        return cls.DATABASE['PRAGMAS']

# Environment-specific configurations
class DevelopmentConfig(Config):
    DEBUG = True
    SERVER = {
        **Config.SERVER,
        'LOG_LEVEL': 'DEBUG'
    }

class ProductionConfig(Config):
    DEBUG = False
    SERVER = {
        **Config.SERVER,
        'LOG_LEVEL': 'WARNING'
    }
    DATABASE = {
        **Config.DATABASE,
        'PRAGMAS': {
            **Config.DATABASE['PRAGMAS'],
            'synchronous': 'NORMAL'  # Better performance
        }
    }

class TestingConfig(Config):
    TESTING = True
    DATABASE = {
        **Config.DATABASE,
        'NAME': Config.DATABASE['TEST_NAME']
    }
    SERVER = {
        **Config.SERVER,
        'PORT': 8889  # Different port for testing
    }

# Configuration selector
def get_config(env: str = None) -> Config:
    env = env or os.getenv('CHAT_ENV', 'development').lower()
    configs = {
        'development': DevelopmentConfig,
        'production': ProductionConfig,
        'testing': TestingConfig
    }
    return configs.get(env, DevelopmentConfig)

# Current active configuration
current_config = get_config()