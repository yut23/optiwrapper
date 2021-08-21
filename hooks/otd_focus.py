from . import otd


class Hook(otd.Hook):
    """Change OTD settings while focused"""

    def on_focus(self) -> None:
        self.on_start()

    def on_unfocus(self) -> None:
        self.on_stop()
