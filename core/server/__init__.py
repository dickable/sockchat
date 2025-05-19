import asyncio
import logging
import os
import importlib.util

from core.server.views.login import prompt_login
from core.server.views.register import prompt_register
from core.database import DatabaseManager

# Logger setup
logger = logging.getLogger("chat-server")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

db = DatabaseManager("assets/chat.db")
clients = []  # list of (reader, writer, username)
chat_history = []
clear_offsets = {}
user_histories = {}
user_hist_pos = {}

# Message of the Day
MOTD = "Welcome to the Async Chat! Be respectful and have fun."
CLEAR_SCREEN = "\x1b[2J\x1b[H"
COMMANDS = {}


def strip_telnet_iac(data: bytes) -> bytes:
    """Remove Telnet IAC command sequences (IAC CMD OPT) from input bytes."""
    res = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 255:  # IAC
            # skip IAC and next two bytes if present
            i += 3
        else:
            res.append(data[i])
            i += 1
    return bytes(res)


def load_commands(commands_dir="core/server/commands"):
    for fname in os.listdir(commands_dir):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        path = os.path.join(commands_dir, fname)
        name = fname[:-3]
        spec = importlib.util.spec_from_file_location(f"commands.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cmd = getattr(mod, "COMMAND_NAME", None)
        handler = getattr(mod, "handle", None)
        is_admin = getattr(mod, "ADMIN_COMMAND", False)
        if cmd and handler and asyncio.iscoroutinefunction(handler):
            COMMANDS[cmd] = (handler, is_admin)


async def render_screen(writer):
    offset = clear_offsets.get(writer, 0)
    header = f"*** MOTD: {MOTD} ***\r\n--- Chat ---\r\n"
    body = "\r\n".join(chat_history[offset:])
    writer.write((CLEAR_SCREEN + header + body).encode())
    await writer.drain()


async def broadcast(message: str):
    chat_history.append(message)
    for _, w, _ in clients:
        try:
            await render_screen(w)
        except:
            pass


async def read_input(reader, writer):
    buf = []
    pos = 0
    user_histories.setdefault(writer, [])
    user_hist_pos[writer] = len(user_histories[writer])
    writer.write(b"> ")
    await writer.drain()
    while True:
        data = await reader.read(32)
        if not data:
            return None
        data = strip_telnet_iac(data)
        for ch in data:
            b = bytes([ch])
            # Enter
            if b in (b"\r", b"\n"):
                writer.write(b"\r\n")
                await writer.drain()
                line = ''.join(buf)
                user_histories[writer].append(line)
                user_hist_pos[writer] = len(user_histories[writer])
                return line
            # Backspace
            if ch == 127:
                if pos > 0:
                    buf.pop(pos-1)
                    pos -= 1
                    writer.write(b"\x1b[2K\r> " + ''.join(buf).encode())
                    writer.write(f"\x1b[{len(buf)-pos}D".encode())
                    await writer.drain()
                continue
            # Arrow sequences handled in strip_telnet_iac, here b is literal
            if ch == 27:
                continue
            # Regular char
            buf.insert(pos, chr(ch))
            tail = ''.join(buf[pos+1:])
            writer.write(chr(ch).encode() + tail.encode() + f"\x1b[{len(tail)}D".encode())
            pos += 1
            await writer.drain()


async def handle_command(text: str, username: str, writer):
    parts = text.lstrip("/").split()
    cmd = parts[0].lower()
    args = parts[1:]
    if cmd in ("quit", "exit", "q"):
        return "__QUIT__"
    if cmd == "clear":
        clear_offsets[writer] = len(chat_history)
        await render_screen(writer)
        return None
    if cmd == "motd":
        global MOTD
        if args:
            MOTD = " ".join(args)
            await broadcast(f"*** MOTD updated by {username} ***")
        else:
            writer.write(f"Current MOTD: {MOTD}\r\n".encode())
            await writer.drain()
        return None
    if cmd == "help":
        builtins = ["/help", "/clear", "/motd", "/quit"]
        custom = [f"/{c}" for c, (_, a) in COMMANDS.items() if not a]
        writer.write(b"Available commands:\r\n")
        for l in builtins + custom:
            writer.write(f"  {l}\r\n".encode())
        await writer.drain()
        return None
    entry = COMMANDS.get(cmd)
    if entry:
        h, _ = entry
        await h(args, {"username": username, "broadcast": broadcast, "writer": writer})
    else:
        writer.write(f"Unknown command: /{cmd}\r\n".encode())
        await writer.drain()
    return None


async def chat_session(reader, writer, username: str):
    clients.append((reader, writer, username))
    clear_offsets[writer] = 0
    await broadcast(f"*** {username} joined ***")
    try:
        await render_screen(writer)
        while True:
            line = await read_input(reader, writer)
            if line is None:
                break
            if line.startswith("/"):
                if await handle_command(line, username, writer) == "__QUIT__":
                    break
            else:
                await broadcast(f"{username}: {line}")
    finally:
        clients.remove((reader, writer, username))
        await broadcast(f"*** {username} left ***")
        writer.close()
        await writer.wait_closed()
        logger.info(f"{username} disconnected")


async def choose_option(reader, writer, options):
    while True:
        menu = f"*** MOTD: {MOTD} ***\r\n"
        menu += "========== MENU ==========" + "\r\n"
        for i, line in enumerate(options, 1):
            menu += f"  {i}) {line}\r\n"
        menu += "==========================\r\nEnter choice: "
        data = await reader.readline()
        if not data:
            return None
        data = strip_telnet_iac(data)
        choice = data.decode(errors='ignore').strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        writer.write(b"Invalid option, try again.\r\n")
        await writer.drain()


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    logger.info(f"New connection: {addr}")
    choice = await choose_option(reader, writer, ["Login", "Register"])
    if choice is None:
        writer.close()
        return
    if choice == 0:
        u, p = await prompt_login(addr, reader, writer)
        if not db.user_exists(u) or not db.verify_password(u, p):
            writer.write(b"Invalid credentials\r\n")
            await writer.drain(); writer.close(); return
        writer.write(b"Logged in\r\n"); await writer.drain(); username = u
    else:
        u, p, c = await prompt_register(addr, reader, writer)
        if p != c or db.user_exists(u):
            writer.write(b"Registration error\r\n")
            await writer.drain(); writer.close(); return
        db.create_user(u, p)
        writer.write(b"Registered, please login\r\n"); await writer.drain(); writer.close(); return
    load_commands()
    await chat_session(reader, writer, username)


async def run_server(host="0.0.0.0", port=12345):
    serv = await asyncio.start_server(handle_client, host, port)
    logger.info(f"Serving on {serv.sockets[0].getsockname()}")
    async with serv:
        await serv.serve_forever()