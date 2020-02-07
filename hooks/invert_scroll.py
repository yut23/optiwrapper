import subprocess

from . import WrapperHook, logger, run


class Hook(WrapperHook):
    def on_start(self) -> None:
        pass

    def on_focus(self) -> None:
        try:
            run(
                [
                    "xinput",
                    "set-button-map",
                    "Logitech M510",
                    *"1 2 3 5 4 6 7 8 9".split(),
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            logger.exception(__name__)

    def on_unfocus(self) -> None:
        try:
            run(
                [
                    "xinput",
                    "set-button-map",
                    "Logitech M510",
                    *"1 2 3 4 5 6 7 8 9".split(),
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            logger.exception(__name__)
