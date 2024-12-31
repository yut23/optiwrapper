import xml.etree.ElementTree as ET
from pathlib import Path

from optiwrapper.hooks import WrapperHook, WrongWindowManagerError, run


class Hook(WrapperHook):
    """Disable focus-follows-mouse (Openbox)"""

    config_path = Path.home() / ".config/openbox/rc.xml"

    def __init__(self, window_manager: str) -> None:
        if "Openbox" not in window_manager:
            raise WrongWindowManagerError()

    async def on_focus(self) -> None:
        tree = ET.parse(self.config_path)
        node = tree.find(
            "./focus/followMouse", namespaces={"": "http://openbox.org/3.4/rc"}
        )
        if node is not None:
            node.text = "no"
            tree.write(self.config_path)
            run(["openbox", "--reconfigure"])

    async def on_unfocus(self) -> None:
        tree = ET.parse(self.config_path)
        node = tree.find(
            "./focus/followMouse", namespaces={"": "http://openbox.org/3.4/rc"}
        )
        if node is not None:
            node.text = "yes"
            tree.write(self.config_path)
            run(["openbox", "--reconfigure"])
