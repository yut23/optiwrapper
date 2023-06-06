from . import WrapperHook, run


class Hook(WrapperHook):
    """Stop ananicy while focused"""

    def __init__(self) -> None:
        self.stopped = False

    async def on_start(self) -> None:
        pass

    async def on_focus(self) -> None:
        if not self.stopped:
            run(["sudo", "/usr/bin/systemctl", "stop", "ananicy"])
            self.stopped = True

    async def on_stop(self) -> None:
        if self.stopped:
            run(["sudo", "/usr/bin/systemctl", "start", "ananicy"])
