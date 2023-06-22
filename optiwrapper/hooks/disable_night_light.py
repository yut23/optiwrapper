from dbus_next import DBusError
from dbus_next.aio import MessageBus, ProxyInterface

from optiwrapper.hooks import WrapperHook

NAME = "org.gnome.SettingsDaemon.Color"
PATH = "/org/gnome/SettingsDaemon/Color"
INTERFACE = NAME


class Hook(WrapperHook):
    """Disable blue light filter (GNOME)"""

    def __init__(self) -> None:
        self.enabled = False
        self._color: ProxyInterface

    async def initialize(self) -> None:
        try:
            bus = await MessageBus().connect()
            introspection = await bus.introspect(NAME, PATH)
            obj = bus.get_proxy_object(NAME, PATH, introspection)
            self._color = obj.get_interface(INTERFACE)
            self.enabled = (
                await self._color.get_night_light_active()  # type: ignore[attr-defined]
                and not await self._color.get_disabled_until_tomorrow()  # type: ignore[attr-defined]
            )
        except DBusError:
            pass

    async def on_start(self) -> None:
        if self.enabled:
            try:
                await self._color.set_disabled_until_tomorrow(False)  # type: ignore[attr-defined]
            except DBusError:
                pass

    async def on_stop(self) -> None:
        if self.enabled:
            try:
                await self._color.set_disabled_until_tomorrow(False)  # type: ignore[attr-defined]
            except DBusError:
                pass
