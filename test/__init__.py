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
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'backend'))  # server package lives in backend/

__all__ = []