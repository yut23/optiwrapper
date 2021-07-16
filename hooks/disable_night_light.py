from gi.repository import GLib
from pydbus import SessionBus

from . import WrapperHook

bus = SessionBus()
INTERFACE = "org.gnome.SettingsDaemon.Color"


class Hook(WrapperHook):
    def __init__(self) -> None:
        self.enabled = False
        try:
            color = bus.get(INTERFACE)
            self.enabled = color.NightLightActive and not color.DisabledUntilTomorrow
        except GLib.GError:
            pass

    def on_start(self) -> None:
        if self.enabled:
            try:
                bus.get(INTERFACE).DisabledUntilTomorrow = True
            except GLib.GError:
                pass

    def on_stop(self) -> None:
        if self.enabled:
            try:
                bus.get(INTERFACE).DisabledUntilTomorrow = False
            except GLib.GError:
                pass
