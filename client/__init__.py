"""
Client package for chatroom application.

Provides:
- ChatClient: Main client connection class
- Command-line and GUI interfaces
"""

from .chat_client import ChatClient

__all__ = ['ChatClient']
__version__ = '1.0.0'