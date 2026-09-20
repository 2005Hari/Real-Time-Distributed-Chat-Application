"""
Server package for distributed chatroom application.

Exposes main components for external use:
- ChatServer: Main WebSocket server class
- SQLService: Database operations handler
"""

from .sql_service import SQLService
from .database import init_db

__all__ = ['SQLService', 'init_db']
__version__ = '1.0.0'