from . import WrapperHook, run


class Hook(WrapperHook):
    def __init__(self) -> None:
        self.stopped = False

    def on_start(self) -> None:
        pass

    def on_focus(self) -> None:
        if not self.stopped:
            run(["sudo", "/usr/bin/systemctl", "stop", "ananicy"])
            self.stopped = True

    def on_stop(self) -> None:
        if self.stopped:
            run(["sudo", "/usr/bin/systemctl", "start", "ananicy"])
