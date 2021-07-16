from . import WrapperHook, run


class Hook(WrapperHook):
    def on_stop(self) -> None:
        run(["autorandr", "-c"], check=False)
