from . import WrapperHook


class Hook(WrapperHook):
    """Short description"""

    def __init__(self) -> None:
        pass

    # async def initialize(self) -> None:
    #     pass

    # async def on_start(self) -> None:
    #     await self.on_focus()

    async def on_focus(self) -> None:
        pass

    async def on_unfocus(self) -> None:
        pass

    # async def on_stop(self) -> None:
    #     await self.on_unfocus()
