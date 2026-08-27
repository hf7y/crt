import asyncio, os, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Loopback stays the default: on dexter that is the bind, and README's
# never-bind-0.0.0.0 rule is unaffected by which URL a CLIENT dials.
# ZAXON_URL is for the tailnet callers the port is already open to --
# an agent on mandark or monkey can reach dexter:8643 but could not use
# this client at all, because the address it needs was not reachable
# from outside the source file.
URL = os.environ.get('ZAXON_URL', 'http://127.0.0.1:8643/mcp')

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
