import re
import subprocess

from . import WrapperHook


class Hook(WrapperHook):
    def __init__(self) -> None:
        self.enabled = True
        output = subprocess.check_output(["/usr/bin/synclient", "-l"], text=True)
        # if touchpad is already disabled, don't re-enable it when the game stops
        self.enabled = re.search(r"^TouchpadOff\s*=\s*1$", output) is None

    def on_start(self) -> None:
        if self.enabled:
            subprocess.run(["/usr/bin/synclient", "TouchpadOff=1"], check=False)

    def on_stop(self) -> None:
        if self.enabled:
            subprocess.run(["/usr/bin/synclient", "TouchpadOff=0"], check=False)
