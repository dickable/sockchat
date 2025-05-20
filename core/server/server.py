import asyncio
import logging
import os
import importlib.util
import socket

from core.server.views.login import prompt_login
from core.server.views.register import prompt_register
from core.database import DatabaseManager

IAC  = 255
DONT = 254
DO   = 253
WILL = 251
ECHO = 1
SGA  = 3

ESC = b'\x1b'
CSI = b'\x1b['
MOVE_LEFT  = lambda n: f'\x1b[{n}D'.encode()
MOVE_RIGHT = lambda n: f'\x1b[{n}C'.encode()
CLEAR_EOL  = b'\x1b[K'
CLEAR_SCREEN = "\x1b[2J\x1b[H"  # ANSI: clear screen + home

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
MOTD = "hey thanks for meowing"
COMMANDS = {}

async def negotiate_telnet(writer):
    writer.write(bytes([IAC, WILL, ECHO, IAC, DONT, ECHO, IAC, WILL, SGA, IAC, DO, SGA]))
    await writer.drain()

def strip_telnet_iac(data: bytes) -> bytes:
    result = bytearray()
    i = 0
    while i < len(data):
        if data[i] == IAC:
            if i + 1 >= len(data): break
            cmd = data[i+1]
            if cmd in (DO, DONT, WILL): i += 3
            elif cmd == IAC: result.append(IAC); i += 2
            else: i += 2
        else:
            result.append(data[i])
            i += 1
    return bytes(result)

def load_commands(commands_dir="core/server/commands"):
    for fname in os.listdir(commands_dir):
        if not fname.endswith(".py") or fname.startswith("__"): continue
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
    # Clear screen, set scrolling region, print MOTD and chat
    writer.write(b"\x1b[2J\x1b[1;21r\x1b[1;1H")
    writer.write((header + body).encode())
    # Separator and prompt
    writer.write(b"\x1b[22;1H\x1b[2K-------------------\r\n")
    writer.write(b"\x1b[23;1H\x1b[2K$~/ ")  # Clear line, write prompt
    await writer.drain()

async def redraw_input_line(writer, prompt: bytes, buf, pos):
    writer.write(b"\x1b[23;1H\x1b[2K")  # Move to line 23, clear line
    writer.write(prompt + b"".join([c.encode() for c in buf]))
    col = len(prompt) + 1 + pos
    writer.write(f"\x1b[23;{col}H".encode())
    await writer.drain()

async def read_input(reader, writer, prompt_str="$~/ "):
    await negotiate_telnet(writer)
    prompt = prompt_str.encode()
    buf = []
    pos = 0
    user_histories.setdefault(writer, [])
    user_hist_pos[writer] = len(user_histories[writer])

    while True:
        data = await reader.read(1)
        if not data: return None
        data = strip_telnet_iac(data)
        if not data: continue
        ch = data[0]

        if ch in (13, 10):  # ENTER
            line = "".join(buf)
            if line:
                user_histories[writer].append(line)
            user_hist_pos[writer] = len(user_histories[writer])
            return line

        if ch == 27:  # Arrow keys
            seq = await reader.read(2)
            if seq[:1] == b'[':
                code = seq[1:2]
                if code == b'D' and pos > 0:  # Left arrow
                    pos -= 1
                    writer.write(MOVE_LEFT(1))
                elif code == b'C' and pos < len(buf):  # Right arrow
                    pos += 1
                    writer.write(MOVE_RIGHT(1))
                await writer.drain()
            continue

        if ch in (127, 8):  # BACKSPACE
            if pos > 0:
                buf.pop(pos-1)
                pos -= 1
                await redraw_input_line(writer, prompt, buf, pos)
            continue

        if 32 <= ch <= 126 or ch > 127:  # Printable characters
            c = chr(ch)
            buf.insert(pos, c)
            pos += 1
            await redraw_input_line(writer, prompt, buf, pos)
            continue

async def handle_command(text: str, username: str, writer):
    global MOTD
    parts = text.lstrip("/").split()
    cmd = parts[0].lower()
    args = parts[1:]
    if cmd in ("quit", "exit", "q"):
        return "__QUIT__"
    if cmd == "clear":
        clear_offsets[writer] = len(chat_history)  # Hide history for this user
        # Fully reset screen for this user
        writer.write(b"\x1b[2J\x1b[1;21r\x1b[1;1H")
        writer.write(f"*** MOTD: {MOTD} ***\r\n--- Chat ---\r\n".encode())
        writer.write(b"\x1b[22;1H\x1b[2K-------------------\r\n")
        writer.write(b"\x1b[23;1H\x1b[2K$~/ ")  # Clear line, write prompt
        await writer.drain()
        return None
    if cmd == "motd":
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
    writer.write(b"\x1b[2J\x1b[1;21r\x1b[1;1H")
    writer.write(f"*** MOTD: {MOTD} ***\r\n--- Chat ---\r\n".encode())
    writer.write(b"\x1b[22;1H\x1b[2K-------------------\r\n")
    writer.write(b"\x1b[23;1H\x1b[2K$~/ ")
    await writer.drain()
    await broadcast(f"*** {username} joined ***")
    try:
        while True:
            line = await read_input(reader, writer)
            if line is None:
                break
            if line.startswith("/"):
                if await handle_command(line, username, writer) == "__QUIT__":
                    break
            elif line.strip():
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
        writer.write(menu.encode())
        await writer.drain()
        data = await reader.readline()
        if not data:
            return None
        data = strip_telnet_iac(data)
        choice = data.decode(errors='ignore').strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        writer.write(b"Invalid option, try again.\r\n")
        await writer.drain()

async def broadcast(message: str):
    chat_history.append(message)
    for _, w, _ in clients:
        try:
            await render_screen(w)
        except:
            pass

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