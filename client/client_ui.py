import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import asyncio
import websockets
import json
from threading import Thread
from datetime import datetime

class ChatClientUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat Client")
        self.websocket = None
        self.username = None
        self.user_id = None
        self.private_chats = {}
        self.loop = asyncio.new_event_loop()
        
        self.setup_ui()
        Thread(target=self.start_loop, daemon=True).start()

    def setup_ui(self):
        self.root.geometry("1000x700")
        
        # Connection Frame
        conn_frame = ttk.Frame(self.root)
        conn_frame.pack(pady=10)
        
        ttk.Label(conn_frame, text="Server:").pack(side=tk.LEFT)
        self.server_entry = ttk.Entry(conn_frame, width=25)
        self.server_entry.pack(side=tk.LEFT, padx=5)
        self.server_entry.insert(0, "ws://localhost:8888")
        
        ttk.Label(conn_frame, text="Username:").pack(side=tk.LEFT)
        self.username_entry = ttk.Entry(conn_frame, width=15)
        self.username_entry.pack(side=tk.LEFT, padx=5)
        
        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT)

        # Chat area
        chat_area = ttk.Frame(self.root)
        chat_area.pack(fill=tk.BOTH, expand=True)

        # Chat Display
        self.chat_display = scrolledtext.ScrolledText(
            chat_area, wrap=tk.WORD, state='disabled', font=('Arial', 11)
        )
        self.chat_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure message tags
        for tag, color in [('public', 'black'), ('private', 'blue'), 
                          ('system', 'green'), ('error', 'red'), 
                          ('notification', 'purple')]:
            self.chat_display.tag_config(tag, foreground=color)

        # Right sidebar
        sidebar = ttk.Frame(chat_area, width=200)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))

        # Online Users
        ttk.Label(sidebar, text="Online Users").pack()
        self.user_list = ttk.Treeview(sidebar, height=15, show="tree", selectmode='browse')
        self.user_list.pack(fill=tk.BOTH, pady=(0, 10))
        self.user_list.bind('<Double-1>', self.on_user_double_click)

        # Private Chats
        ttk.Label(sidebar, text="Private Chats").pack()
        self.private_chats_list = ttk.Treeview(sidebar, height=10, show="tree", selectmode='browse')
        self.private_chats_list.pack(fill=tk.BOTH)
        self.private_chats_list.bind('<Double-1>', self.on_private_chat_double_click)

        # Message Input
        input_frame = ttk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.message_entry = ttk.Entry(input_frame, font=('Arial', 11))
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message)
        
        self.send_btn = ttk.Button(input_frame, text="Send", command=self.send_message)
        self.send_btn.pack(side=tk.RIGHT)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Disconnected")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X)

    def start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def connect(self):
        if self.websocket and not getattr(self.websocket, 'closed', False):
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
            return
            
        asyncio.run_coroutine_threadsafe(self.connect_async(), self.loop)

    async def connect_async(self):
        server_url = self.server_entry.get()
        self.username = self.username_entry.get().strip()
        
        if not self.username:
            self.show_error("Username is required")
            return
            
        try:
            self.websocket = await websockets.connect(server_url)
            self.user_id = str(hash(self.username))  # Simple ID generation
            
            # Register with server
            await self.websocket.send(json.dumps({
                "type": "register",
                "username": self.username,
                "user_id": self.user_id
            }))
            
            # Start receiving messages
            asyncio.create_task(self.receive_messages())
            
            self.update_ui(connected=True)
            self.update_status("Connected")
            
        except Exception as e:
            self.show_error(f"Connection failed: {str(e)}")
            self.update_ui(connected=False)

    async def receive_messages(self):
        try:
            while True:
                message = await self.websocket.recv()
                self.handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            self.display_message("Disconnected from server", 'system')
            self.update_ui(connected=False)
        except Exception as e:
            self.show_error(f"Error receiving messages: {str(e)}")

    def handle_message(self, raw_message):
        try:
            message = json.loads(raw_message)
            msg_type = message.get('type')
            
            if msg_type == 'welcome':
                self.display_message(message['message'], 'system')
            elif msg_type == 'user_list':
                self.update_user_list(message.get('users', []))
            elif msg_type == 'public_message':
                self.display_message(
                    f"[{self.format_time(message['timestamp'])}] {message['sender']}: {message['content']}",
                    'public'
                )
            elif msg_type == 'private_message':
                self.handle_private_message(message)
            elif msg_type == 'private_chat_start':
                self.handle_new_private_chat(message)
            elif msg_type == 'error':
                self.display_message(f"Error: {message['message']}", 'error')

        except json.JSONDecodeError:
            self.show_error("Invalid message from server")

    def on_user_double_click(self, event):
        """Handle double-click on user list to start private chat"""
        selection = self.user_list.selection()
        if selection:
            selected_user = self.user_list.item(selection)['text']
            if selected_user != self.username:
                self.start_private_chat(selected_user)

    def start_private_chat(self, username):
        """Initiate a private chat with selected user"""
        if not self.websocket:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.websocket.send(json.dumps({
                "type": "private_request",
                "recipient": username
            })),
            self.loop
        )

    def on_private_chat_double_click(self, event):
        """Handle double-click on private chat list to open chat window"""
        selection = self.private_chats_list.selection()
        if selection:
            chat_id = self.private_chats_list.item(selection)['text']
            if chat_id in self.private_chats:
                other_user = self.private_chats[chat_id]['other_user']
                self.create_private_chat_window(chat_id, other_user)

    def handle_private_message(self, message):
        """Handle incoming private message"""
        chat_id = message['chat_id']
        formatted_msg = f"[{self.format_time(message['timestamp'])}] [Private] {message['sender']}: {message['content']}"
        
        if chat_id in self.private_chats:
            # Display in private chat window
            self.display_private_message(chat_id, formatted_msg)
        else:
            # Display notification in main chat
            self.display_message(
                f"[Private] New message from {message['sender']}: {message['content']}",
                'notification'
            )

    def handle_new_private_chat(self, message):
        """Handle new private chat creation"""
        chat_id = message['chat_id']
        other_user = message['other_user']
        
        if chat_id not in self.private_chats:
            self.private_chats[chat_id] = {
                'other_user': other_user,
                'unread': 0
            }
            self.update_private_chats_list()
            
            # Create window if not exists
            self.create_private_chat_window(chat_id, other_user)
        
        self.display_message(
            f"Private chat started with {other_user} (ID: {chat_id})",
            'system'
        )

    def create_private_chat_window(self, chat_id, other_user):
        """Create a new window for private chat"""
        if chat_id in self.private_chats and 'window' in self.private_chats[chat_id]:
            # Bring existing window to front
            self.private_chats[chat_id]['window'].lift()
            return
            
        window = tk.Toplevel(self.root)
        window.title(f"Private Chat with {other_user}")
        window.geometry("600x500")
        
        # Chat display
        display = scrolledtext.ScrolledText(
            window, wrap=tk.WORD, state='disabled', font=('Arial', 11)
        )
        display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Input area
        input_frame = ttk.Frame(window)
        input_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        entry = ttk.Entry(input_frame, font=('Arial', 11))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", lambda e: self.send_private_message(chat_id, entry))
        
        send_btn = ttk.Button(input_frame, text="Send", 
                            command=lambda: self.send_private_message(chat_id, entry))
        send_btn.pack(side=tk.RIGHT)
        
        # Store window reference
        self.private_chats[chat_id]['window'] = window
        self.private_chats[chat_id]['display'] = display
        self.private_chats[chat_id]['entry'] = entry
        
        # Request chat history
        if self.websocket:
            asyncio.run_coroutine_threadsafe(
                self.request_chat_history(chat_id),
                self.loop
            )
        
        # Handle window closing
        window.protocol("WM_DELETE_WINDOW", 
                      lambda: self.close_private_chat(chat_id))

    async def request_chat_history(self, chat_id):
        """Request chat history for a private chat"""
        await self.websocket.send(json.dumps({
            "type": "chat_history_request",
            "chat_id": chat_id
        }))

    def display_private_message(self, chat_id, message):
        """Display message in private chat window"""
        if chat_id not in self.private_chats:
            return
            
        display = self.private_chats[chat_id]['display']
        display.config(state=tk.NORMAL)
        display.insert(tk.END, message + '\n', 'private')
        display.config(state=tk.DISABLED)
        display.see(tk.END)
        
        # Mark as read
        self.private_chats[chat_id]['unread'] = 0
        self.update_private_chats_list()

    def close_private_chat(self, chat_id):
        """Close private chat window"""
        if chat_id in self.private_chats and 'window' in self.private_chats[chat_id]:
            self.private_chats[chat_id]['window'].destroy()
            del self.private_chats[chat_id]['window']
            del self.private_chats[chat_id]['display']
            del self.private_chats[chat_id]['entry']
            self.update_private_chats_list()

    def send_message(self, event=None):
        """Send public chat message"""
        message = self.message_entry.get().strip()
        if not message or not self.websocket:
            return
            
        if message.startswith('/'):
            self.handle_command(message)
        else:
            asyncio.run_coroutine_threadsafe(
                self.send_public_message(message),
                self.loop
            )
        
        self.message_entry.delete(0, tk.END)

    def send_private_message(self, chat_id, entry_widget, event=None):
        """Send private message"""
        message = entry_widget.get().strip()
        if not message or not self.websocket:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.websocket.send(json.dumps({
                "type": "private_message",
                "chat_id": chat_id,
                "content": message
            })),
            self.loop
        )
        
        entry_widget.delete(0, tk.END)

    async def send_public_message(self, message):
        """Send public message to server"""
        try:
            await self.websocket.send(json.dumps({
                "type": "public_message",
                "content": message
            }))
        except Exception as e:
            self.show_error(f"Failed to send message: {str(e)}")

    def handle_command(self, command):
        """Handle chat commands"""
        if command.lower() == '/help':
            help_text = """Available commands:
/public - Switch to public chat
/private <username> - Start private chat
/clear - Clear chat history
/help - Show this help"""
            self.display_message(help_text, 'system')
        elif command.lower() == '/clear':
            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.delete(1.0, tk.END)
            self.chat_display.config(state=tk.DISABLED)
        elif command.lower().startswith('/private '):
            username = command[9:].strip()
            if username:
                self.start_private_chat(username)
        else:
            self.display_message(f"Unknown command: {command}", 'error')

    def update_user_list(self, users):
        """Update the online users list"""
        self.user_list.delete(*self.user_list.get_children())
        for user in users:
            self.user_list.insert("", tk.END, text=user['username'], values=(user['user_id']))

    def update_private_chats_list(self):
        """Update the private chats list"""
        self.private_chats_list.delete(*self.private_chats_list.get_children())
        for chat_id, chat_data in self.private_chats.items():
            unread = f" ({chat_data['unread']})" if chat_data.get('unread', 0) > 0 else ""
            self.private_chats_list.insert(
                "", tk.END, 
                text=chat_id, 
                values=(f"{chat_data['other_user']}{unread}")
            )

    def update_ui(self, connected):
        """Update UI elements based on connection state"""
        state = tk.DISABLED if connected else tk.NORMAL
        self.connect_btn.config(
            text="Disconnect" if connected else "Connect",
            command=self.disconnect if connected else self.connect
        )
        self.username_entry.config(state=state)
        self.server_entry.config(state=state)
        self.message_entry.config(state=tk.NORMAL if connected else tk.DISABLED)
        self.send_btn.config(state=tk.NORMAL if connected else tk.DISABLED)

    def update_status(self, message):
        """Update status bar message"""
        self.status_var.set(message)

    def display_message(self, message, tag='public'):
        """Display message in main chat window"""
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, message + '\n', tag)
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def format_time(self, timestamp_str):
        """Format timestamp for display"""
        try:
            dt = datetime.fromisoformat(timestamp_str)
            return dt.strftime("%H:%M")
        except:
            return ""

    def show_error(self, message):
        """Show error message dialog"""
        messagebox.showerror("Error", message)

    async def disconnect(self):
        """Disconnect from server"""
        if self.websocket:
            await self.websocket.close()
        self.update_ui(connected=False)

    def on_closing(self):
        """Handle window closing"""
        if self.websocket and not getattr(self.websocket, 'closed', False):
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()