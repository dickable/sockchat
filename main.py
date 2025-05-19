import argparse
import logging
import signal
import sys
import asyncio

from core.config import ConfigManager
from core.server import run_server

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

def shutdown_handler(sig, frame):
    logging.info("Shutting down server...")
    sys.exit(0)

async def main_async():
    parser = argparse.ArgumentParser(description="TCP Chat Server")
    parser.add_argument('--host', help='Host to bind', default=None)
    parser.add_argument('--port', type=int, help='Port to bind', default=None)
    args = parser.parse_args()

    config = ConfigManager("assets/config.json")
    host = args.host or config.get("host", "0.0.0.0")
    port = args.port or config.get("port", 12345)

    logging.info(f"Starting server on {host}:{port}")
    await run_server(host, port)

def main():
    # catch Ctrl+C for a clean exit
    signal.signal(signal.SIGINT, shutdown_handler)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logging.info("Server shutdown requested")

if __name__ == "__main__":
    main()
