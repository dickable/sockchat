import socket

def render_register_prompt():
    return (
        "\x1b[2J\x1b[H"
        "================================\r\n"
        "|           REGISTER           |\r\n"
        "|    Create a new account      |\r\n"
        "================================\r\n"
        "New Username: "
    )

async def prompt_register(conn, reader, writer):
    # Send prompt
    writer.write(render_register_prompt().encode())
    await writer.drain()

    # Read new username
    username = (await reader.readline()).decode().strip()

    # Ask for password
    writer.write(b"New Password: ")
    await writer.drain()
    password = (await reader.readline()).decode().strip()

    # Confirm password
    writer.write(b"Confirm Password: ")
    await writer.drain()
    confirm = (await reader.readline()).decode().strip()

    return username, password, confirm