import glob
import importlib
import logging
import os
import subprocess
from os.path import dirname, join, realpath, split, splitext
from typing import Any, Dict, Type

from ..lib import remove_overlay

logger = logging.getLogger(__name__)
WINDOW_MANAGER = ""


def run(
    *args: Any, is_32_bit: bool = False, **kwargs: Any
) -> "subprocess.CompletedProcess[Any]":
    """run(args: _CMD, bufsize: int, executable: Optional[AnyPath], stdin: _FILE, stdout: _FILE, stderr: _FILE, preexec_fn: Callable[[], Any], close_fds: bool, shell: bool, cwd: Optional[AnyPath], env: Optional[_ENV], universal_newlines: bool, startupinfo: Any, creationflags: int, restore_signals: bool, start_new_session: bool, pass_fds: Any, *, is_32_bit: bool, capture_output: bool, check: bool, encoding: Optional[str], errors: Optional[str], input: Optional[_TXT], text: Optional[bool], timeout: Optional[float]) -> CompletedProcess[Any]

    Run command with arguments and return a CompletedProcess instance.

    The returned instance will have attributes args, returncode, stdout and
    stderr. By default, stdout and stderr are not captured, and those attributes
    will be None. Pass stdout=PIPE and/or stderr=PIPE in order to capture them.

    If check is True and the exit code was non-zero, it raises a
    CalledProcessError. The CalledProcessError object will have the return code
    in the returncode attribute, and output & stderr attributes if those streams
    were captured.

    If timeout is given, and the process takes too long, a TimeoutExpired
    exception will be raised.

    There is an optional argument "input", allowing you to
    pass bytes or a string to the subprocess's stdin.  If you use this argument
    you may not also use the Popen constructor's "stdin" argument, as
    it will be used internally.

    By default, all communication is in bytes, and therefore any "input" should
    be bytes, and the stdout and stderr will be bytes. If in text mode, any
    "input" should be a string, and stdout and stderr will be strings decoded
    according to locale encoding, or by "encoding" if set. Text mode is
    triggered by setting any of text, encoding, errors or universal_newlines.

    The other arguments are the same as for the Popen constructor."""
    kwargs = kwargs.copy()
    env_override = remove_overlay(is_32_bit)
    if "env" in kwargs:
        kwargs["env"].update(env_override)
    else:
        kwargs["env"] = {**os.environ, **env_override}
    if "check" not in kwargs:
        kwargs["check"] = True
    return subprocess.run(*args, **kwargs)  # pylint: disable=subprocess-run-check


run.__doc__ = subprocess.run.__doc__


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


_REGISTERED_HOOKS: Dict[str, Type[WrapperHook]] = {}
_LOADED_HOOKS: Dict[str, WrapperHook] = {}


def load_hook(name: str) -> None:
    if "=" in name:
        name, _args = name.split("=", maxsplit=1)
        args = _args.split(",")
    else:
        args = []
    if name not in _REGISTERED_HOOKS:
        raise ValueError(f"Hook not found: {name!r}")
    _LOADED_HOOKS[name] = _REGISTERED_HOOKS[name](*args)
    logger.debug("loaded hook %r", name)


def get_hooks() -> Dict[str, WrapperHook]:
    return _LOADED_HOOKS


def register_hooks() -> None:
    basedir = dirname(realpath(__file__))

    for filename in glob.glob(join(basedir, "*.py")):
        module = splitext(split(filename)[-1])[0]
        if not module.startswith("_"):
            try:
                _REGISTERED_HOOKS[module] = importlib.import_module(
                    __name__ + "." + module
                ).Hook
            except ImportError as ex:
                logger.debug("Failed to load %r hook:", module, exc_info=ex)
                logger.warning("Ignoring exception while loading the %r hook.", module)
