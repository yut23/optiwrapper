from typing import Iterable, List

from gi.repository import Gio

from . import WINDOW_MANAGER, WrapperHook, run


class Hook(WrapperHook):
    """Fix shift key in LWJGL games"""

    XKB_OPTIONS_SCHEMA = "org.gnome.desktop.input-sources"
    XKB_OPTIONS_KEY = "xkb-options"
    BAD_OPTION = "shift:both_capslock"

    def __init__(self) -> None:
        self.enabled = False
        self.gnome = "GNOME" in WINDOW_MANAGER
        self.original: List[str]
        self.modified: List[str]
        if self.gnome:
            self.gsettings = Gio.Settings.new(self.XKB_OPTIONS_SCHEMA)
            self.original = self.gsettings.get_strv(self.XKB_OPTIONS_KEY)
        else:
            proc = run(
                ["setxkbmap", "-query"], check=False, capture_output=True, text=True
            )
            if proc.returncode != 0:
                return
            opts_line = next(
                (l for l in proc.stdout.splitlines() if l.startswith("options: ")), ""
            )
            if not opts_line:
                return
            self.original = opts_line[: len("options: ")].strip().split(",")

        if self.BAD_OPTION in self.original:
            self.enabled = True
            # get unique elements
            self.modified = list(set(self.original))
            self.modified.remove(self.BAD_OPTION)

    def _set_options(self, opts: Iterable[str]) -> None:
        if self.gnome:
            self.gsettings.set_strv(self.XKB_OPTIONS_KEY, opts)
        else:
            # passing an empty -option will replace all existing options
            args = ["-option"]
            for opt in opts:
                args.extend(["-option", opt])
            run(["setxkbmap", *args], check=False)

    def on_start(self) -> None:
        pass

    def on_focus(self) -> None:
        if self.enabled:
            self._set_options(self.modified)

    def on_unfocus(self) -> None:
        if self.enabled:
            self._set_options(self.original)
