import asyncio
import time

from gi.events import GLibEventLoopPolicy
from gi.repository import GLib  # noqa: E402
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

# Set up the GLib event loop
policy = GLibEventLoopPolicy()
asyncio.set_event_loop_policy(policy)
glib_main =  GLib.MainLoop()

asyncio_loop = policy.get_event_loop()

async def do_some_work():
    await asyncio.sleep(2)
    print("Done working!")

task = asyncio_loop.create_task(do_some_work())

def filter_handler(address, *args):
    print(f"{address}: {args}")
    return ("/", f"Hello {args[0]} at {time.ctime()}")

dispatcher = Dispatcher()
dispatcher.map("/filter", filter_handler)



async def start_osc():
    global transport
    server = AsyncIOOSCUDPServer(("127.0.0.1", 9000), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()  # Create datagram endpoint and start serving
    
    print("STARTED OSC")

task2 = asyncio_loop.create_task(start_osc())

try:
    glib_main.run()
except KeyboardInterrupt:
    transport.close()
    print("Closed transport")

