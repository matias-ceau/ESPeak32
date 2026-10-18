"""Minimal BlueZ pairing agent for Linux: accepts Just Works confirmation for one device only.

LE Secure Connections "Just Works" makes BlueZ ask the default agent to confirm; without an agent able to answer,
pairing fails with "Numeric comparison failed". bleak has no agent, so `just_works_agent()` registers one for the
duration of a connection. It never handles passkeys or PINs and rejects every other device.
"""

import contextlib
from typing import AsyncIterator

AGENT_PATH = "/net/espeak32/agent"


def device_matches(device_path: str, address: str) -> bool:
    return device_path.rsplit("/", 1)[-1] == "dev_" + address.upper().replace(":", "_")


@contextlib.asynccontextmanager
async def just_works_agent(address: str) -> AsyncIterator[None]:
    from dbus_fast import BusType, DBusError
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, method

    def check(device: str) -> None:
        if not device_matches(device, address):
            raise DBusError("org.bluez.Error.Rejected", "not the ESPeak32 being paired")

    class Agent(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):  # noqa: N802 (D-Bus names)
            pass

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: F821, N802
            check(device)

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821, N802
            check(device)

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821, N802
            check(device)

        @method()
        def Cancel(self):  # noqa: N802
            pass

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    bus.export(AGENT_PATH, Agent())
    intro = await bus.introspect("org.bluez", "/org/bluez")
    manager = bus.get_proxy_object("org.bluez", "/org/bluez", intro).get_interface("org.bluez.AgentManager1")
    await manager.call_register_agent(AGENT_PATH, "NoInputNoOutput")
    await manager.call_request_default_agent(AGENT_PATH)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await manager.call_unregister_agent(AGENT_PATH)
        bus.disconnect()
