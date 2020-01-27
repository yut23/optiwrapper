import subprocess

from . import WrapperHook


class Hook(WrapperHook):
    def on_focus(self) -> None:
        subprocess.run(["/home/eric/bin/mouse-accel", "off"], check=False)

    def on_unfocus(self) -> None:
        subprocess.run(["/home/eric/bin/mouse-accel", "on"], check=False)
