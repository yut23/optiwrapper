import importlib
import inspect
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Type

from optiwrapper.lib import clean_ld_preload

logger = logging.getLogger(__name__)


class WrongWindowManagerError(Exception):
    pass


def run(
    *args: Any, is_32_bit: bool = False, **kwargs: Any
) -> "subprocess.CompletedProcess[Any]":
    # pylint: disable-next=line-too-long
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
    env_override = clean_ld_preload(not is_32_bit)
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
    env_override = clean_ld_preload(not is_32_bit)
    if "env" in kwargs:
        kwargs["env"].update(env_override)
    else:
        kwargs["env"] = {**os.environ, **env_override}
    kwargs["text"] = True
    return subprocess.check_output(*args, **kwargs)  # type: ignore


class WrapperHook:
    async def initialize(self) -> None:
        """Will be called immediately after __init__."""

    async def on_start(self) -> None:
        """Will be run when the game starts."""
        await self.on_focus()

    async def on_stop(self) -> None:
        """Will be run when the game stops."""
        await self.on_unfocus()

    async def on_focus(self) -> None:
        """Will be run when the game window gains focus."""

    async def on_unfocus(self) -> None:
        """Will be run when the game window loses focus."""


_REGISTERED_HOOKS: Dict[str, Type[WrapperHook]] = {}
_LOADED_HOOKS: Dict[str, WrapperHook] = {}


async def load_hook(name: str, **kwargs: Any) -> None:
    """The keyword arguments cfg, gpu_type, and window_manager (attributes from
    optiwrapper.wrapper.Main) will be passed to each hook's __init__(), if
    requested.
    """
    if "=" in name:
        name, _args = name.split("=", maxsplit=1)
        args = _args.split(",")
    else:
        args = []
    if name not in _REGISTERED_HOOKS:
        raise ValueError(f"Hook not found: {name!r}")
    if name not in _LOADED_HOOKS:
        hook_class = _REGISTERED_HOOKS[name]
        sig = inspect.signature(hook_class, eval_str=False)
        kws = {k: v for k, v in kwargs.items() if k in sig.parameters}
        try:
            _LOADED_HOOKS[name] = hook_class(*args, **kws)
        except WrongWindowManagerError:
            logger.debug(
                "skipping hook %r: in wrong window manager %r",
                name,
                kwargs.get("window_manager"),
            )
            return
        await _LOADED_HOOKS[name].initialize()
        logger.debug("loaded hook %r", name)
    else:
        logger.warning("hook %r already loaded", name)


def get_loaded_hooks() -> Dict[str, WrapperHook]:
    return _LOADED_HOOKS


def get_all_hooks() -> Dict[str, Type[WrapperHook]]:
    return _REGISTERED_HOOKS


def register_hooks() -> None:
    basedir = Path(__file__).resolve().parent

    for path in basedir.glob("*.py"):
        module = path.stem
        if module.startswith("_") or module == "template":
            continue
        try:
            _REGISTERED_HOOKS[module] = importlib.import_module(
                f"{__name__}.{module}"
            ).Hook
        except ImportError as ex:
            logger.debug("Failed to load %r hook:", module, exc_info=ex)
            logger.warning("Ignoring exception while loading the %r hook.", module)
