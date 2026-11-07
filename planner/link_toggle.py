"""T15 demo switch: tell the system the network dropped (or came back).

    python -m planner.link_toggle off      # status/link {"online": false}
    python -m planner.link_toggle on       # status/link {"online": true}

Sends one {topic, data} envelope to the hub's /ws. The hub must accept `status/link` from clients
(it is not in BROWSER_TOPICS yet; asked on the board). In-process code can call `await set_link(bus, False)`.
"""

import argparse
import asyncio
import json


async def set_link(bus, online: bool):
    await bus.publish("status/link", {"online": online})


async def send(url: str, online: bool):
    import websockets  # pip install websockets

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"topic": "status/link", "data": {"online": online}}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--url", default="ws://localhost:8000/ws")
    a = p.parse_args()
    asyncio.run(send(a.url, a.state == "on"))
    print(f"status/link online={a.state == 'on'} sent to {a.url}")


if __name__ == "__main__":
    main()
