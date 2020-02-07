import re

from . import WrapperHook, check_output, run


class Hook(WrapperHook):
    def __init__(self) -> None:
        self.enabled = True
        output = check_output(["/usr/bin/synclient", "-l"])
        # if touchpad is already disabled, don't re-enable it when the game stops
        self.enabled = re.search(r"^TouchpadOff\s*=\s*1$", output) is None

    def on_start(self) -> None:
        if self.enabled:
            run(["/usr/bin/synclient", "TouchpadOff=1"], check=True)

    def on_stop(self) -> None:
        if self.enabled:
            run(["/usr/bin/synclient", "TouchpadOff=0"], check=True)
