from . import otd


class Hook(otd.Hook):
    """Change OTD settings while focused"""

    async def on_focus(self) -> None:
        await self.on_start()

    async def on_unfocus(self) -> None:
        await self.on_stop()
