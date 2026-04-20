# Distributed Chat App

A Python-based real-time chat application with a WebSocket server, a Tkinter GUI client, and SQLite persistence. It supports public chat, private 1:1 chats, online user presence, and basic history.

## Features

- Real-time messaging over WebSockets
- Public room + private 1:1 chats
- Online users list and presence
- SQLite database with indexes and foreign keys
- GUI client built with Tkinter
- Basic test suite with pytest

## Tech Stack

- Python 3.11+
- websockets (async WebSocket server/client)
- sqlite3 (local persistence)
- Tkinter (desktop GUI)
- pytest (tests)

## Project Structure

```
DistributedChatApp/
├─ client/               # Client applications
│  ├─ client_ui.py       # Tkinter GUI client (recommended)
│  └─ chat_client.py     # Minimal CLI client (experimental)
├─ server/               # WebSocket server and data layer
│  ├─ chat_server.py     # WebSocket server (public + private chats)
│  ├─ sql_service.py     # SQLite schema + queries
│  ├─ database.py        # DB helpers (if needed by server)
│  └─ client_handler.py  # Additional server handlers
├─ config/
│  └─ config.py          # Centralized configuration
├─ test/                 # Pytest test files
├─ requirements.txt      # Python dependencies
└─ .env                  # Local env (not committed)
```

## Quick Start

1) Create and activate a virtual environment

```
python -m venv .venv
.\u005c.venv\Scripts\activate  # Windows PowerShell
# source .venv/bin/activate   # macOS/Linux
```

2) Install dependencies

```
pip install -r requirements.txt
```

3) Run the WebSocket server

```
python server/chat_server.py
# Server listens on ws://localhost:8888 by default
```

4) Run the GUI client (recommended)

```
python client/client_ui.py
```

You can open multiple GUI clients to simulate different users.

## Configuration

- App configuration is in `config/config.py` with environment profiles for development, production, and testing.
- Select a profile via environment variable `CHAT_ENV` (defaults to `development`).
  - Examples: `CHAT_ENV=production`, `CHAT_ENV=testing`
- Database is a local SQLite file `chatroom.db` (auto-created). It is excluded from Git.

## Protocol (high level)

- On connect, the client must send a registration message:
  ```json
  { "type": "register", "username": "alice", "user_id": "<uuid-or-stable-id>" }
  ```
- Public message broadcast:
  ```json
  { "type": "public_message", "content": "Hello everyone" }
  ```
- Start a private chat:
  ```json
  { "type": "private_request", "recipient": "bob" }
  ```
- Send a private message:
  ```json
  { "type": "private_message", "chat_id": "<chat-id>", "content": "hi" }
  ```

The GUI client (`client_ui.py`) implements this protocol end-to-end.

## Testing

```
pytest -q
```

## Notes

- Do not commit secrets or local files: `.env`, `.venv/`, `chatroom.db` are ignored by Git.
- The minimal CLI client `chat_client.py` is experimental and may not fully match the server’s latest message protocol. Prefer the GUI client.

