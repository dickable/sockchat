import socket

def render_login_prompt():
    # You can adjust positions later; simple text for now
    return (
        "\x1b[2J\x1b[H"
        "================================\r\n"
        "|            WELCOME           |\r\n"
        "|        Please login:         |\r\n"
        "================================\r\n"
        "Username: "
    )

async def prompt_login(conn, reader, writer):
    # Send prompt
    writer.write(render_login_prompt().encode())
    await writer.drain()

    # Read username
    username = (await reader.readline()).decode().strip()

    # Ask for password
    writer.write(b"Password: ")
    await writer.drain()
    password = (await reader.readline()).decode().strip()

    return username, password