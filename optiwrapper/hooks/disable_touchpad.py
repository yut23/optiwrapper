import fcntl

from . import WrapperHook, check_output, run

touchpad_cmd = "/home/eric/bin/mandelbrot/touchpad"
lock_file = "/var/lib/touchpad/disable.lock"


class Hook(WrapperHook):
    """Disable laptop touchpad"""

    def __init__(self) -> None:
        self.enabled = True
        output = check_output([touchpad_cmd, "get"])
        # if touchpad is already disabled, don't re-enable it when the game stops
        self.enabled = "on" in output
        # obtain a shared lock on the lock file, to block the touchpad from
        # turning on when the mouse turns off.
        self.fd = open(lock_file, "r")  # pylint: disable=consider-using-with
        fcntl.flock(self.fd, fcntl.LOCK_SH)

    def on_start(self) -> None:
        if self.enabled:
            run([touchpad_cmd, "off"], check=True)

    def on_stop(self) -> None:
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()
        if self.enabled:
            run([touchpad_cmd, "auto"], check=True)
