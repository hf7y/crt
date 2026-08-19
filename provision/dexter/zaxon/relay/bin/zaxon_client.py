import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = 'http://127.0.0.1:8643/mcp'

async def ask(question, from_agent):
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool('ask_zach', {'question': question, 'from_agent': from_agent})
            print(r.content[0].text)

async def check(ticket_id):
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool('check_zach_reply', {'ticket_id': ticket_id})
            print(r.content[0].text)

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'ask':
        asyncio.run(ask(sys.argv[2], sys.argv[3]))
    elif cmd == 'check':
        asyncio.run(check(sys.argv[2]))
