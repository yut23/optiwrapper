"""
Cribbed from gnome-shell-extension-tool.
"""

import os
import subprocess
from typing import Any, Dict

from lib import logger, remove_overlay


def get_kwargs(subcommand: str, uuid: str) -> Dict[str, Any]:
    kwargs = {
        "args": ["/usr/bin/gnome-extensions", subcommand, uuid],
        "text": True,
    }
    # remove 32-bit steam overlay from LD_PRELOAD
    env_override = remove_overlay()
    logger.debug(env_override)
    if env_override:
        kwargs["env"] = {**os.environ, **env_override}
    return kwargs


def enable_extension(uuid: str) -> None:
    """
    Enables the extension with `uuid`.
    """
    subprocess.run(check=True, **get_kwargs("enable", uuid))


def disable_extension(uuid: str) -> None:
    """
    Disables the extension with `uuid`.
    """
    subprocess.run(check=True, **get_kwargs("disable", uuid))


def is_extension_enabled(uuid: str) -> bool:
    """
    Returns True if the extension with `uuid` is enabled.
    """
    return "State: ENABLED" in subprocess.check_output(**get_kwargs("info", uuid))
