#!/usr/bin/env python3
"""Login, list chargers, connect to the relay and print decoded status frames.

Usage: python3 tools/probe.py EMAIL PASSWORD [DEVICE_NUMBER]
"""

import asyncio
import logging
import os
import sys

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.abb_chargersync.api import AbbCloudClient, AbbRelayClient  # noqa: E402

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")


async def main(email: str, password: str, want: str | None = None) -> None:
    async with aiohttp.ClientSession() as session:
        cloud = AbbCloudClient(session, email, password)
        await cloud.login()
        user = await cloud.get_user()
        print("user id", user["id"])
        devices = await cloud.get_devices()
        for dev in devices:
            print(
                "device",
                dev["id"],
                dev["deviceNumber"],
                "online=",
                dev.get("online"),
                "status=",
                dev.get("status"),
                "rated=",
                dev.get("ratedCurrent"),
                "model=",
                dev.get("model"),
            )
        dev = next((d for d in devices if d["deviceNumber"] == want), devices[0])
        relay = AbbRelayClient(session, cloud, dev["deviceNumber"], int(dev["id"]))
        await relay.ensure_session()
        print("auth ok fw=", relay.firmware_version, "hw=", relay.hardware_version)
        print("power:", await relay.read_power_control())
        for _ in range(3):
            print("status:", await relay.read_status())
            await asyncio.sleep(5)
        await relay.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
