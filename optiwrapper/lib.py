#!/usr/bin/env python3
"""
Common functions and variables used in multiple modules.
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, Generator, Iterable, List, Optional

from proc.core import Process, find_processes
from Xlib import X, display, error
from Xlib.protocol import event

logger = logging.getLogger("optiwrapper")

# Paths
WRAPPER_DIR = Path.home() / "Games/wrapper"
SETTINGS_DIR = WRAPPER_DIR / "settings"

# Used to tell focus thread to stop
running = True


# implement os.pidfd_open using ctypes if it's not available
# 2023-06-05: conda-forge's python is built on CentOS 7, which runs Linux 3.10
if not hasattr(os, "pidfd_open"):
    import platform

    if platform.system() == "Linux" and tuple(
        map(int, platform.release().partition("-")[0].split("."))
    ) >= (5, 3, 0):
        import ctypes

        libc = ctypes.CDLL(None)
        _syscall = libc.syscall

        def _pidfd_open(pid, flags=0):
            """Return a file descriptor referring to the process *pid*.

            The descriptor can be used to perform process management without races and
            signals.
            """
            return _syscall(434, pid, flags)

        os.pidfd_open = _pidfd_open


def watch_focus(
    window_ids: Iterable[int],
    focus_in_cb: Callable[[Optional[event.FocusIn]], None],
    focus_out_cb: Callable[[Optional[event.FocusOut]], None],
) -> Generator[int, None, None]:
    """Watches for focus changes and executes callbacks.

    Watches for focus changes on all windows in `window_ids`, and executes the
    corresponding callback with the specified event.

    Args:
        window_ids: A list of X window IDs to track.
        focus_in_cb: A function to execute when a window gains focus. The focus
            event will be passed as the first argument.
        focus_out_cb: A function to execute when a window loses focus. The focus
            event will be passed as the first argument.

    Yields:
        Each window ID when that window closes.
        -1 if a window ID is invalid and returns early.
        Returns early if game is stopped (lib.running changes to False)
    """
    disp = display.Display()
    focused = disp.get_input_focus().focus

    # subscribe to focus events on each window
    ec = error.CatchError(error.BadWindow)
    for window_id in window_ids:
        win = disp.create_resource_object("window", window_id)
        win.change_attributes(
            event_mask=X.FocusChangeMask | X.StructureNotifyMask, onerror=ec
        )
        disp.sync()
        err = ec.get_error()
        if err:
            logger.error("Bad window ID: 0x%x", err.resource_id.id)
            yield -1
            return
        if win == focused:
            focus_in_cb(None)
        else:
            focus_out_cb(None)

    # main loop
    while running:
        evt = disp.next_event()
        if not running:
            break
        if evt.type == X.DestroyNotify:
            logger.debug("window destroyed: 0x%x", evt.window.id)
            yield int(evt.window.id)
        if isinstance(evt, event.Focus):
            if evt.mode not in (X.NotifyNormal, X.NotifyWhileGrabbed):
                continue
            if isinstance(evt, event.FocusIn) and focused != evt.window:
                focus_in_cb(evt)
                focused = evt.window
            if (
                isinstance(evt, event.FocusOut)
                and focused == evt.window
                and evt.detail != X.NotifyInferior
            ):
                focus_out_cb(evt)
                focused = X.NONE

    yield 0


def pgrep(pattern: str, match_full: bool = False) -> List[Process]:
    """Works like the pgrep command. Searches /proc for a matching process.

    Args:
        pattern: A regular expression to match against.

    Kwargs:
        match_full: If True, match against `/proc/<pid>/cmdline` instead of
            `/proc/<pid>/comm` (which is limited to 15 characters).

    Returns:
        A list of matching processes.
    """

    regex = re.compile(pattern)
    own_pid = str(os.getpid())

    procs = set()
    for proc in find_processes():
        if proc.pid == own_pid or not proc.cmdline:
            continue

        if match_full:
            for val in proc.cmdline:
                if regex.search(val) is not None:
                    # found match
                    procs.add(proc)
                    break
            if regex.search(" ".join(proc.cmdline)) is not None:
                procs.add(proc)
        else:
            # only match against argv[0]
            if regex.search(proc.cmdline[0]) is not None:
                # found match
                procs.add(proc)

    return list(procs)


def clean_ld_preload(is_64_bit: bool) -> Dict[str, str]:
    if is_64_bit:
        bad_lib = "ubuntu12_32"
    else:
        bad_lib = "ubuntu12_64"
    screensaver_fix = "sdl_block_screensaver_inhibit.so"

    def is_good(entry: str) -> bool:
        return bad_lib not in entry and screensaver_fix not in entry

    orig_entries = os.environ.get("LD_PRELOAD", "").split(":")
    cleaned_entries = list(filter(is_good, orig_entries))
    if cleaned_entries != orig_entries:
        # need to override the environment variable
        return {"LD_PRELOAD": ":".join(cleaned_entries)}
    return {}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <window id>")
        sys.exit(1)

    DETAIL_LUT = {
        X.NotifyAncestor: "NotifyAncestor",
        X.NotifyVirtual: "NotifyVirtual",
        X.NotifyInferior: "NotifyInferior",
        X.NotifyNonlinear: "NotifyNonlinear",
        X.NotifyNonlinearVirtual: "NotifyNonlinearVirtual",
        X.NotifyPointer: "NotifyPointer",
        X.NotifyPointerRoot: "NotifyPointerRoot",
        X.NotifyDetailNone: "NotifyDetailNone",
    }

    def focus_in(evt: Optional[event.FocusIn]) -> None:
        """Prints message about the window that got focus."""
        if evt is None:
            return
        cls = evt.window.get_wm_class() or ("", "")
        print(
            'Got  focus on window 0x{:07x} ({:s}) "{:s}"'.format(
                evt.window.id, DETAIL_LUT[evt.detail], cls[1]
            )
        )

    def focus_out(evt: Optional[event.FocusOut]) -> None:
        """Prints message about the window that lost focus."""
        if evt is None:
            return
        cls = evt.window.get_wm_class() or ("", "")
        print(
            'Lost focus on window 0x{:07x} ({:s}) "{:s}"'.format(
                evt.window.id, DETAIL_LUT[evt.detail], cls[1]
            )
        )

    sys.exit(
        next(watch_focus([int(arg, 0) for arg in sys.argv[1:]], focus_in, focus_out))
    )
