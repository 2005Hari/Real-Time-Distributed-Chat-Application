"""
Test suite for chatroom application.

Contains:
- Server tests
- Database tests
- Client tests
"""
import os
import sys

# Ensure tests can import from parent directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

__all__ = []