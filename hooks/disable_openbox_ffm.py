import xml.etree.ElementTree as ET
from pathlib import Path

from . import WrapperHook, run


class Hook(WrapperHook):
    """Disable focus-follows-mouse (Openbox)"""

    config_path = Path.home() / ".config/openbox/rc.xml"

    def on_focus(self) -> None:
        tree = ET.parse(self.config_path)
        node = tree.find(
            "./focus/followMouse", namespaces={"": "http://openbox.org/3.4/rc"}
        )
        if node is not None:
            node.text = "no"
            tree.write(self.config_path)
            run(["openbox", "--reconfigure"])

    def on_unfocus(self) -> None:
        tree = ET.parse(self.config_path)
        node = tree.find(
            "./focus/followMouse", namespaces={"": "http://openbox.org/3.4/rc"}
        )
        if node is not None:
            node.text = "yes"
            tree.write(self.config_path)
            run(["openbox", "--reconfigure"])
