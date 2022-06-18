"""
Python implementation of gnome-extensions-tool.
<https://gitlab.gnome.org/fmuellner/gnome-extensions-tool>
"""

from gi.repository import GLib
from pydbus import SessionBus

bus = SessionBus()


def enable_extension(uuid: str) -> None:
    """
    Enables the extension with `uuid`.
    """
    try:
        shell = bus.get("org.gnome.Shell")
        shell.EnableExtension(uuid)
    except GLib.GError:
        pass


def disable_extension(uuid: str) -> None:
    """
    Disables the extension with `uuid`.
    """
    try:
        shell = bus.get("org.gnome.Shell")
        shell.DisableExtension(uuid)
    except GLib.GError:
        pass


def is_extension_enabled(uuid: str) -> bool:
    """
    Returns True if the extension with `uuid` is enabled.
    """
    try:
        shell = bus.get("org.gnome.Shell")
        return bool(shell.GetExtensionInfo(uuid).get("state", -1) == 1)
    except GLib.GError:
        return False
