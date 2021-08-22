from Xlib import display

from . import WrapperHook


class Hook(WrapperHook):
    """Invert mouse scroll direction"""

    def __init__(self) -> None:
        self.display = display.Display()

    def on_start(self) -> None:
        pass

    def on_focus(self) -> None:
        old_map = self.display.get_pointer_mapping()
        new_map = old_map.copy()
        new_map[3:5] = [5, 4]
        self.display.set_pointer_mapping(new_map)

    def on_unfocus(self) -> None:
        old_map = self.display.get_pointer_mapping()
        new_map = old_map.copy()
        new_map[3:5] = [4, 5]
        self.display.set_pointer_mapping(new_map)
