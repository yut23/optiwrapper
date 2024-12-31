from dbus_next import DBusError
from dbus_next.aio import MessageBus, ProxyInterface

from optiwrapper.hooks import WrapperHook
from optiwrapper.settings import Config

NAME = "org.freedesktop.ScreenSaver"
PATH = "/org/freedesktop/ScreenSaver"
INTERFACE = NAME


class Hook(WrapperHook):
    """Manually inhibit the X screensaver through the DBus interface"""

    def __init__(self, cfg: Config) -> None:
        self.game = cfg.game
        self.cookie: int | None = None
        self._screensaver: ProxyInterface | None = None

    async def initialize(self) -> None:
        try:
            bus = await MessageBus().connect()
            introspection = await bus.introspect(NAME, PATH)
            obj = bus.get_proxy_object(NAME, PATH, introspection)
            self._screensaver = obj.get_interface(INTERFACE)
        except DBusError:
            pass

    async def on_focus(self) -> None:
        if self._screensaver is not None:
            application_name = "optiwrapper"
            reason = f"playing {self.game}"
            try:
                self.cookie = await self._screensaver.inhibit(application_name, reason)  # type: ignore[attr-defined]
            except DBusError:
                self.cookie = None

    async def on_unfocus(self) -> None:
        if self._screensaver is not None and self.cookie is not None:
            try:
                await self._screensaver.uninhibit(self.cookie)  # type: ignore[attr-defined]
            except DBusError:
                pass
            finally:
                self.cookie = None
