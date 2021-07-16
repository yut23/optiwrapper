from . import WrapperHook, run


class Hook(WrapperHook):
    def __init__(self, cfg_name: str):
        self.cfg_name = cfg_name

    def on_start(self) -> None:
        run(["otd", "load", self.cfg_name], check=False)

    def on_stop(self) -> None:
        run(["otd", "load", "desktop.json"], check=False)
