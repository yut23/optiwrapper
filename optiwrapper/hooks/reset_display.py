from optiwrapper.hooks import WrapperHook, run


class Hook(WrapperHook):
    """Reset display settings on exit"""

    async def on_stop(self) -> None:
        run(["autorandr", "-c"], check=False)
