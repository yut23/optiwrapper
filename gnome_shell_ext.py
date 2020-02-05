"""
Cribbed from gnome-shell-extension-tool.
"""

import subprocess


def enable_extension(uuid: str) -> None:
    """
    Enables the extension with `uuid`.
    """
    subprocess.run(["/usr/bin/gnome-extensions", "enable", uuid], check=True)


def disable_extension(uuid: str) -> None:
    """
    Disables the extension with `uuid`.
    """
    subprocess.run(["/usr/bin/gnome-extensions", "disable", uuid], check=True)


def is_extension_enabled(uuid: str) -> bool:
    """
    Returns True if the extension with `uuid` is enabled.
    """
    output = subprocess.check_output(
        ["/usr/bin/gnome-extensions", "info", uuid], text=True
    )
    return "State: ENABLED" in output
