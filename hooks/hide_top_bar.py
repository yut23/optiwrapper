import gnome_shell_ext

from . import WrapperHook

UUID = "hidetopbar@mathieu.bidon.ca"


class Hook(WrapperHook):
    """Hide top panel (GNOME)"""

    def __init__(self) -> None:
        self.enabled = True
        self.enabled = not gnome_shell_ext.is_extension_enabled(UUID)

    def on_start(self) -> None:
        if self.enabled:
            gnome_shell_ext.enable_extension(UUID)

    def on_stop(self) -> None:
        if self.enabled:
            gnome_shell_ext.disable_extension(UUID)
