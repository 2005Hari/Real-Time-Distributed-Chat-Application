import json

class ClientHandler:
    def __init__(self, username, websocket, server):
        self.username = username
        self.websocket = websocket
        self.server = server
        self.current_chat = None

    async def handle_message(self, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "public_message":
                await self.handle_public_message(data)
            elif msg_type == "private_request":
                await self.handle_private_request(data)
            elif msg_type == "private_response":
                await self.handle_private_response(data)
            elif msg_type == "private_message":
                await self.handle_private_message(data)
            elif msg_type == "end_private_chat":
                await self.handle_end_private_chat()
            elif msg_type == "set_username":
                await self.handle_set_username(data)
            else:
                await self.send_error("Unknown message type")

        except json.JSONDecodeError:
            await self.send_error("Invalid JSON format")
        except Exception as e:
            await self.send_error(f"Error processing message: {str(e)}")

    async def handle_public_message(self, data):
        content = data.get("content")
        if content:
            await self.server.send_system_message(f"{self.username}: {content}")

    async def handle_private_request(self, data):
        receiver = data.get("receiver")
        if receiver:
            await self.server.initiate_private_chat(self.username, receiver)

    async def handle_private_response(self, data):
        accepted = data.get("accepted", False)
        await self.server.process_private_response(self.username, accepted)

    async def handle_private_message(self, data):
        content = data.get("content")
        if self.current_chat and content:
            await self.server.send_private_message(self.current_chat, self.username, content)

    async def handle_end_private_chat(self):
        if self.current_chat:
            await self.server.end_private_chat(self.current_chat, self.username)
            self.current_chat = None

    async def handle_set_username(self, data):
        new_username = data.get("username")
        if new_username and new_username not in self.server.clients:
            old_username = self.username
            self.server.clients[new_username] = self.server.clients.pop(old_username)
            self.server.client_handlers[new_username] = self.server.client_handlers.pop(old_username)
            self.username = new_username
            await self.send_success(f"Username changed to {new_username}")
            await self.server.broadcast_user_list()
        else:
            await self.send_error("Username unavailable")

    async def send_error(self, message):
        await self.websocket.send(json.dumps({
            "type": "error",
            "message": message
        }))

    async def send_success(self, message):
        await self.websocket.send(json.dumps({
            "type": "success",
            "message": message
        }))