from optiwrapper.hooks import WrapperHook
from optiwrapper.lib import pgrep


class Hook(WrapperHook):
    """Suspend xcape while focused"""

    def __init__(self) -> None:
        self.xcape_procs = pgrep("xcape .*Control_L", match_full=True)

    async def on_focus(self) -> None:
        for xcape_proc in self.xcape_procs:
            xcape_proc.suspend()

    async def on_unfocus(self) -> None:
        for xcape_proc in self.xcape_procs:
            xcape_proc.resume()
