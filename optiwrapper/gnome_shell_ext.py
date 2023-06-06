"""
Python implementation of gnome-extensions-tool.
<https://gitlab.gnome.org/fmuellner/gnome-extensions-tool>
"""

from dbus_next import DBusError, Variant
from dbus_next.aio import MessageBus, ProxyInterface

NAME = "org.gnome.Shell"
PATH = "/org/gnome/Shell"
INTERFACE = "org.gnome.Shell.Extensions"


async def get_shell() -> ProxyInterface:
    bus = await MessageBus().connect()
    introspection = await bus.introspect(NAME, PATH)
    obj = bus.get_proxy_object(NAME, PATH, introspection)
    return obj.get_interface(INTERFACE)


async def enable_extension(uuid: str) -> None:
    """
    Enables the extension with `uuid`.
    """
    try:
        shell = await get_shell()
        shell.call_enable_extension(uuid)  # type: ignore[attr-defined]
    except DBusError:
        pass


async def disable_extension(uuid: str) -> None:
    """
    Disables the extension with `uuid`.
    """
    try:
        shell = await get_shell()
        shell.call_disable_extension(uuid)  # type: ignore[attr-defined]
    except DBusError:
        pass


async def is_extension_enabled(uuid: str) -> bool:
    """
    Returns True if the extension with `uuid` is enabled.
    """
    try:
        shell = await get_shell()
        return bool(
            (await shell.call_enable_extension(uuid))  # type: ignore[attr-defined]
            .get("state", Variant("d", -1))
            .value
            == 1
        )
    except DBusError:
        return False
