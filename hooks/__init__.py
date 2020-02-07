import glob
import importlib
import logging
import os
import subprocess
from os.path import dirname, join, realpath, split, splitext
from typing import Any, Dict, Type

from lib import remove_overlay

logger = logging.getLogger("optiwrapper." + __name__)


def run(
    *args: Any, is_32_bit: bool = False, **kwargs: Any
) -> "subprocess.CompletedProcess[Any]":
    kwargs = kwargs.copy()
    env_override = remove_overlay(is_32_bit)
    if "env" in kwargs:
        kwargs["env"].update(env_override)
    else:
        kwargs["env"] = {**os.environ, **env_override}
    if "check" not in kwargs:
        kwargs["check"] = True
    return subprocess.run(*args, **kwargs)  # pylint: disable=subprocess-run-check


def check_output(*args: Any, is_32_bit: bool = False, **kwargs: Any) -> str:
    kwargs = kwargs.copy()
    env_override = remove_overlay(is_32_bit)
    if "env" in kwargs:
        kwargs["env"].update(env_override)
    else:
        kwargs["env"] = {**os.environ, **env_override}
    kwargs["text"] = True
    return subprocess.check_output(*args, **kwargs)  # type: ignore


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
