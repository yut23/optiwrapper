import glob
import importlib
import logging
from os.path import dirname, join, realpath, split, splitext
from typing import Any, Dict, Type

logger = logging.getLogger("optiwrapper." + __name__)


class WrapperHook:
    def on_start(self) -> None:
        """Will be run when the game starts."""
        self.on_focus()

    def on_stop(self) -> None:
        """Will be run when the game stops."""
        self.on_unfocus()

    def on_focus(self) -> None:
        """Will be run when the game window gains focus."""

    def on_unfocus(self) -> None:
        """Will be run when the game window loses focus."""


_REGISTERED_HOOKS: Dict[str, Type[WrapperHook]] = dict()
_LOADED_HOOKS: Dict[str, WrapperHook] = dict()


def load_hook(name: str) -> None:
    if name not in _REGISTERED_HOOKS:
        raise ValueError(f"Hook not found: {name!r}")
    _LOADED_HOOKS[name] = _REGISTERED_HOOKS[name]()
    logger.debug("loaded hook %r", name)


def get_hooks() -> Dict[str, WrapperHook]:
    return _LOADED_HOOKS


def register_hooks() -> None:
    basedir = dirname(realpath(__file__))
    print(basedir)

    for filename in glob.glob(join(basedir, "*.py")):
        module = splitext(split(filename)[-1])[0]
        if not module.startswith("_"):
            try:
                _REGISTERED_HOOKS[module] = importlib.import_module(  # type: ignore
                    __name__ + "." + module
                ).Hook
            except ImportError:
                logger.warning("Ignoring exception while loading the %r hook.", module)
