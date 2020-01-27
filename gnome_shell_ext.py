"""
Cribbed from gnome-shell-extension-tool.
"""

from gi.repository import Gio

ENABLED_EXTENSIONS_KEY = "enabled-extensions"


def enable_extension(uuid: str) -> None:
    """
    Enables the extension with `uuid`.
    """
    settings = Gio.Settings(schema="org.gnome.shell")
    extensions = settings.get_strv(ENABLED_EXTENSIONS_KEY)

    if uuid not in extensions:
        extensions.append(uuid)
        settings.set_strv(ENABLED_EXTENSIONS_KEY, extensions)


def disable_extension(uuid: str) -> None:
    """
    Disables all extensions with `uuid`.
    """
    settings = Gio.Settings(schema="org.gnome.shell")
    extensions = settings.get_strv(ENABLED_EXTENSIONS_KEY)

    if uuid in extensions:
        # Use a while loop here to remove *all* mentions instances
        # of the extension. Some faulty tools like to append more than one.
        while uuid in extensions:
            extensions.remove(uuid)

        settings.set_strv(ENABLED_EXTENSIONS_KEY, extensions)


def is_extension_enabled(uuid: str) -> bool:
    """
    Returns True if the extension with `uuid` is enabled.
    """
    settings = Gio.Settings(schema="org.gnome.shell")
    extensions = settings.get_strv(ENABLED_EXTENSIONS_KEY)
    return uuid in extensions
