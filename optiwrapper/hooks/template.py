from . import WrapperHook


class Hook(WrapperHook):
    """Short description"""

    def __init__(self) -> None:
        pass

    # def on_start(self) -> None:
    #     self.on_focus()

    def on_focus(self) -> None:
        pass

    def on_unfocus(self) -> None:
        pass

    # def on_stop(self) -> None:
    #     self.on_unfocus()
