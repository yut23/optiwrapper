import gnome_shell_ext

from . import WrapperHook

UUID = "unredirect@vaina.lt"


class Hook(WrapperHook):
    """Enable fullscreen unredirection (GNOME)"""
    def __init__(self) -> None:
        self.enabled = gnome_shell_ext.is_extension_enabled(UUID)

    def on_start(self) -> None:
        if self.enabled:
            # enable fullscreen unredirection (removes intermittent stutter)
            gnome_shell_ext.disable_extension(UUID)

    def on_stop(self) -> None:
        if self.enabled:
            # disable fullscreen unredirection (fixes tearing in videos)
            gnome_shell_ext.enable_extension(UUID)
