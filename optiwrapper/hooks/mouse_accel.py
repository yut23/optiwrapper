import subprocess

from optiwrapper.hooks import WrapperHook, check_output, run

TOOL = "mouse-accel"


class Hook(WrapperHook):
    """Disable mouse acceleration"""

    def __init__(self) -> None:
        self.original_states = {}
        output = check_output([TOOL, "get"], text=True)
        for line in output.strip().split("\n"):
            device, state = line.strip().split(": acceleration ")
            self.original_states[device] = state

    async def on_focus(self) -> None:
        run([TOOL, "off"], stdout=subprocess.DEVNULL, check=False)

    async def on_unfocus(self) -> None:
        for device, state in self.original_states.items():
            run([TOOL, state, device], stdout=subprocess.DEVNULL, check=False)
