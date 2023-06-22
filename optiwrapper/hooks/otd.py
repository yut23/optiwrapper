from optiwrapper.hooks import WrapperHook

# from optiwrapper.hooks import WrapperHook, run


class Hook(WrapperHook):
    """Change OTD settings while running"""

    def __init__(self, cfg_name: str):
        self.cfg_name = cfg_name

    async def on_start(self) -> None:
        run(["otd", "load", self.cfg_name], check=False)

    async def on_stop(self) -> None:
        run(["otd", "load", "desktop.json"], check=False)
