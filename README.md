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

## Deployment: Vercel (frontend) + Render (backend)

The web app is split into two independently deployed parts:

```
frontend/   Static web UI (index.html, app.js, styles.css, config.js, vercel.json) -> Vercel
backend/    FastAPI app: accounts, WebSocket /ws, /upload, /uploads, /health     -> Render
render.yaml Render Blueprint for the backend
```

### Access control

Chat is private: people sign in with a username and password, and **creating an account requires an invite code**
that you choose. Sessions are signed tokens; the WebSocket, uploads and history all require one. Usernames are
unique ignoring case, passwords are hashed with scrypt, and login/sign-up attempts are rate limited.

### 1. Create a free PostgreSQL database (Neon)

Render's free filesystem is wiped on every deploy and whenever the service sleeps, so accounts and messages must
live in an external database.

1. Sign up at [neon.tech](https://neon.tech) and create a project.
2. Copy the connection string (`postgresql://user:password@host/dbname?sslmode=require`). Tables are created
   automatically on first start.

### 2. Deploy the backend on Render

1. Push this repo to GitHub, then in Render choose **New > Blueprint** and select the repo (it reads `render.yaml`).
   Creating a Web Service by hand also works: root directory `backend`, build `pip install -r requirements.txt`,
   start `uvicorn main:app --host 0.0.0.0 --port $PORT`, health check `/health`, and env var `PYTHON_VERSION=3.11.9`.
2. Set the environment variables below in the Render dashboard.
3. Copy the service URL once it is live, e.g. `https://quantumconnect-backend.onrender.com`.
4. After the frontend is deployed (step 3), set `ALLOWED_ORIGINS` to your Vercel URL
   (comma-separated for several, no trailing slash), e.g. `https://my-chat.vercel.app`.

| Env var           | Purpose                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `DATABASE_URL`    | PostgreSQL connection string from step 1. Without it a local SQLite file is used (dev only). |
| `INVITE_CODE`     | Required to create an account. If unset, anyone can register (the server logs a warning).    |
| `SECRET_KEY`      | Signs login sessions. Use a long random string; changing it signs everyone out.              |
| `ALLOWED_ORIGINS` | Origins allowed to call the API (CORS) and open the WebSocket. Defaults to `*`.              |
| `DATA_DIR`        | Where uploads (and the SQLite file, if used) are stored. Defaults to `backend/`.             |
| `PORT`            | Set by Render automatically.                                                                 |

> The Render free plan spins down when idle, so the first connection after a pause can take ~50 seconds. Its
> filesystem is ephemeral, so **uploaded files** are lost on each deploy/restart (accounts and messages are safe in
> Postgres). To keep uploads, use a paid plan with a disk and set `DATA_DIR` to its mount path.

### 3. Deploy the frontend on Vercel

1. Edit `PRODUCTION_BACKEND_URL` in `frontend/config.js` to your Render URL and commit.
2. In Vercel, **Add New > Project**, import the repo and set **Root Directory** to `frontend`.
   Framework preset: **Other**; leave the build command and output directory empty.
3. Deploy, then put the resulting Vercel URL into `ALLOWED_ORIGINS` on Render (step 2.4).

The WebSocket URL (`wss://.../ws`) is derived from that backend URL. It can be changed under **Advanced** on the
sign-in form. Share the site link and the invite code with the people you want in the chat.

### Run the web app locally

```
# terminal 1: backend on http://localhost:8000
cd backend
pip install -r requirements.txt
python main.py

# terminal 2: frontend on http://localhost:3000
cd frontend
python -m http.server 3000
```

`config.js` automatically targets `http://localhost:8000` when the page is opened from `localhost`. Locally the
backend uses a SQLite file and, with no `INVITE_CODE` set, lets you create accounts freely. To develop against
PostgreSQL, set `DATABASE_URL`. Run the tests with `pytest test/test_auth.py` (set `TEST_DATABASE_URL` to run them
on PostgreSQL).

## Quick Start (desktop client)

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

