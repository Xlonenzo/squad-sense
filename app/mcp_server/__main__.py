"""Entry point: `python -m app.mcp_server`."""

import asyncio

from app.mcp_server.server import main

if __name__ == "__main__":
    asyncio.run(main())
