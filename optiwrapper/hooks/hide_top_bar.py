from optiwrapper import gnome_shell_ext
from optiwrapper.hooks import WrapperHook, WrongWindowManagerError

UUID = "hidetopbar@mathieu.bidon.ca"


class Hook(WrapperHook):
    """Hide top panel (GNOME)"""

    def __init__(self, window_manager: str) -> None:
        if "GNOME" not in window_manager:
            raise WrongWindowManagerError()
        self.enabled = True

    async def initialize(self) -> None:
        self.enabled = not await gnome_shell_ext.is_extension_enabled(UUID)

    async def on_start(self) -> None:
        if self.enabled:
            await gnome_shell_ext.enable_extension(UUID)

    async def on_stop(self) -> None:
        if self.enabled:
            await gnome_shell_ext.disable_extension(UUID)
