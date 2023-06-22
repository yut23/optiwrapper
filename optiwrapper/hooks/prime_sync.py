import subprocess

from Xlib import X, display
from Xlib.ext import randr

from optiwrapper.hooks import WrapperHook, run

prop_name = "PRIME Synchronization"


class Hook(WrapperHook):
    """Disable PRIME synchronization"""

    def __init__(self) -> None:
        self.d = display.Display()
        self.outputs = []
        if not self.d.has_extension("RANDR"):
            return
        root = self.d.screen().root
        resources = root.xrandr_get_screen_resources()
        atom = self.d.get_atom(prop_name)
        for output in resources.outputs:
            value = self.d.xrandr_get_output_property(
                output, atom, X.AnyPropertyType, 0, 1
            ).value
            if value and value[0] == 1:
                info = self.d.xrandr_get_output_info(output, resources.config_timestamp)
                if info.connection == randr.Connected:
                    self.outputs.append(info.name)
        self.d.close()

    async def on_start(self) -> None:
        # For some reason, just calling xrandr_change_output_property doesn't work,
        # so we'll let xrandr(1) do the heavy lifting.
        for output in self.outputs:
            run(
                ["xrandr", "--output", output, "--set", prop_name, "0"],
                stdout=subprocess.DEVNULL,
                check=False,
            )

    async def on_stop(self) -> None:
        for output in self.outputs:
            run(
                ["xrandr", "--output", output, "--set", prop_name, "1"],
                stdout=subprocess.DEVNULL,
                check=False,
            )
