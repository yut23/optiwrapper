from optiwrapper.hooks import WrapperHook

# from optiwrapper.hooks import WrapperHook, run


class Hook(WrapperHook):
    """Change OTD settings while running"""

    def __init__(self, cfg_name: str):
        self.cfg_name = cfg_name

    async def on_start(self) -> None:
        # this CLI command doesn't work:
        # https://github.com/OpenTabletDriver/OpenTabletDriver/issues/2536
        # run(["otd", "load", self.cfg_name], check=False)
        pass

    async def on_stop(self) -> None:
        # run(["otd", "load", "desktop.json"], check=False)
        pass
