import asyncio
import websockets
import json
import sys

class ChatClient:
    def __init__(self, server_uri='ws://localhost:8888'):
        self.server_uri = server_uri
        self.websocket = None
        self.username = None
        self.current_chat = None

    async def connect(self):
        self.websocket = await websockets.connect(self.server_uri)
        self.username = f"User{self.websocket.local_address[1]}"
        print(f"Connected as {self.username}")
        await self.receive_messages()

    async def receive_messages(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                self.handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            print("Disconnected from server")
            sys.exit(0)

    def handle_message(self, data):
        msg_type = data.get("type")

        if msg_type == "user_list":
            users = data.get("users", [])
            status = data.get("chat_status", {})
            print("\nOnline users:")
            for user in users:
                print(f" - {user} {'(in private chat)' if status.get(user) else ''}")
            print("> ", end="", flush=True)

        elif msg_type == "system_message":
            print(f"\nSystem: {data.get('content')}")
            print("> ", end="", flush=True)

        elif msg_type == "private_request":
            sender = data.get("sender")
            print(f"\nPrivate chat request from {sender}")
            print("Accept? (y/n) > ", end="", flush=True)

        elif msg_type == "private_chat_started":
            self.current_chat = data.get("chat_id")
            participants = data.get("participants", [])
            other = [p for p in participants if p != self.username][0]
            print(f"\nPrivate chat started with {other}")
            print(f"Type '/exit' to end the chat")
            print("(private) > ", end="", flush=True)

        elif msg_type == "private_message":
            sender = data.get("sender")
            content = data.get("content")
            print(f"\n{sender} (private): {content}")
            print("(private) > ", end="", flush=True)

        elif msg_type == "private_chat_ended":
            initiator = data.get("initiator")
            print(f"\n{initiator} ended the private chat")
            self.current_chat = None
            print("> ", end="", flush=True)

        elif msg_type == "error":
            print(f"\nError: {data.get('message')}")
            print("> ", end="", flush=True)

    async def send_message(self, message):
        if message.startswith('/'):
            await self.handle_command(message)
        else:
            if self.current_chat:
                await self.websocket.send(json.dumps({
                    "type": "private_message",
                    "content": message
                }))
            else:
                await self.websocket.send(json.dumps({
                    "type": "public_message",
                    "content": message
                }))

    async def handle_command(self, command):
        parts = command.split()
        cmd = parts[0].lower()

        if cmd == "/private" and len(parts) > 1:
            await self.websocket.send(json.dumps({
                "type": "private_request",
                "receiver": parts[1]
            }))
        elif cmd == "/accept":
            await self.websocket.send(json.dumps({
                "type": "private_response",
                "accepted": True
            }))
        elif cmd == "/reject":
            await self.websocket.send(json.dumps({
                "type": "private_response",
                "accepted": False
            }))
        elif cmd == "/exit" and self.current_chat:
            await self.websocket.send(json.dumps({
                "type": "end_private_chat"
            }))
        elif cmd == "/name" and len(parts) > 1:
            await self.websocket.send(json.dumps({
                "type": "set_username",
                "username": parts[1]
            }))
        else:
            print("Unknown command")

async def main():
    client = ChatClient()
    await client.connect()

    async def read_input():
        while True:
            message = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
            await client.send_message(message)

    await asyncio.gather(
        client.receive_messages(),
        read_input()
    )

if __name__ == "__main__":
    asyncio.run(main())