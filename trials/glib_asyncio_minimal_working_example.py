import asyncio

from gi.events import GLibEventLoopPolicy
from gi.repository import GLib  # noqa: E402

import gi


# Set up the GLib event loop
policy = GLibEventLoopPolicy()
asyncio.set_event_loop_policy(policy)
glib_main =  GLib.MainLoop()

asyncio_loop = policy.get_event_loop()

async def do_some_work():
    await asyncio.sleep(2)
    print("Done working!")


task = asyncio_loop.create_task(do_some_work())

glib_main.run()

