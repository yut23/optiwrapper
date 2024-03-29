from Xlib import display

from optiwrapper.hooks import WrapperHook


class Hook(WrapperHook):
    """Invert mouse scroll direction"""

    def __init__(self) -> None:
        self.display = display.Display()

    async def on_start(self) -> None:
        pass

    async def on_focus(self) -> None:
        old_map = self.display.get_pointer_mapping()
        new_map = old_map.copy()
        new_map[3:5] = [5, 4]
        self.display.set_pointer_mapping(new_map)

    async def on_unfocus(self) -> None:
        old_map = self.display.get_pointer_mapping()
        new_map = old_map.copy()
        new_map[3:5] = [4, 5]
        self.display.set_pointer_mapping(new_map)
