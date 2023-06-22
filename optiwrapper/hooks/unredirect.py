from optiwrapper import gnome_shell_ext
from optiwrapper.hooks import WrapperHook

UUID = "unredirect@vaina.lt"


class Hook(WrapperHook):
    """Enable fullscreen unredirection (GNOME)"""

    def __init__(self) -> None:
        self.enabled = False

    async def initialize(self) -> None:
        self.enabled = await gnome_shell_ext.is_extension_enabled(UUID)

    async def on_start(self) -> None:
        if self.enabled:
            # enable fullscreen unredirection (removes intermittent stutter)
            await gnome_shell_ext.disable_extension(UUID)

    async def on_stop(self) -> None:
        if self.enabled:
            # disable fullscreen unredirection (fixes tearing in videos)
            await gnome_shell_ext.enable_extension(UUID)
