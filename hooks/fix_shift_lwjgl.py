from gi.repository import Gio

from . import WrapperHook


class Hook(WrapperHook):
    XKB_OPTIONS_SCHEMA = "org.gnome.desktop.input-sources"
    XKB_OPTIONS_KEY = "xkb-options"
    BAD_OPTION = "shift:both_capslock"

    def __init__(self) -> None:
        self.gsettings = Gio.Settings.new(self.XKB_OPTIONS_SCHEMA)
        self.original = self.gsettings.get_strv(self.XKB_OPTIONS_KEY)
        if self.BAD_OPTION in self.original:
            self.modified = self.original.copy()
            self.modified.remove(self.BAD_OPTION)
        else:
            self.gsettings = None

    def on_start(self) -> None:
        pass

    def on_focus(self) -> None:
        if self.gsettings:
            self.gsettings.set_strv(self.XKB_OPTIONS_KEY, self.modified)

    def on_unfocus(self) -> None:
        if self.gsettings:
            self.gsettings.set_strv(self.XKB_OPTIONS_KEY, self.original)
