#!/usr/bin/env python3
"""
Testing interaction with the C watch_focus program from inside python.
"""
# pylint: disable=invalid-name, too-few-public-methods, too-many-arguments
# pylint: disable=too-many-instance-attributes, too-many-locals

import logging
import os
import sys
from ctypes import (
    CDLL,
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_long,
    c_uint,
    c_ulong,
    c_void_p,
    pointer,
)
from typing import Callable, Iterable, List, Optional

from proc.core import Process, find_processes  # type: ignore
from Xlib import X, display, error  # type: ignore

logger = logging.getLogger("optiwrapper")  # pylint: disable=invalid-name

running = True

myxdo = CDLL("/home/eric/Games/wrapper/myxdo.so")

XDO_ERROR = 1
XDO_SUCCESS = 0

# Search only window title. DEPRECATED - Use SEARCH_NAME
SEARCH_TITLE = 1 << 0

# Search only window class.
SEARCH_CLASS = 1 << 1

# Search only window name.
SEARCH_NAME = 1 << 2

# Search only window pid.
SEARCH_PID = 1 << 3

# Search only visible windows.
SEARCH_ONLYVISIBLE = 1 << 4

# Search only a specific screen.
SEARCH_SCREEN = 1 << 5

# Search only window class name.
SEARCH_CLASSNAME = 1 << 6

# Search a specific desktop
SEARCH_DESKTOP = 1 << 7

# Search a specific STEAM_GAME id
SEARCH_STEAM = 1 << 8

window_t = c_ulong


class XdoException(Exception):  # pylint: disable=missing-docstring
    def __init__(self, code, msg):
        # type: (int, str) -> None
        super(XdoException, self).__init__(msg)
        self.code = code


def _errcheck_cb(result, func, arguments):
    """
    Error checker for functions returning an integer indicating
    success (0) / failure (1).

    Raises a XdoException in case of error, otherwise just
    returns ``None`` (returning the original code, 0, would be
    useless anyways..)
    """

    if result != 0:
        raise XdoException(
            result, "Function {0} returned error code {1}".format(func.__name__, result)
        )


class xdo_t(Structure):
    """The main context"""

    _fields_ = [
        # The Display for Xlib
        # Display *xdpy;
        ("xdpy", c_void_p),
        # The display name, if any. NULL if not specified.
        #   char *display_name;
        ("display_name", c_char_p),
        # Should we close the display when calling xdo_free?
        #   int close_display_when_freed;
        ("close_display_when_freed", c_int),
        # Be extra quiet? (omits some error/message output)
        #   int quiet;
        ("quiet", c_int),
        # Enable debug output?
        #   int debug;
        ("debug", c_int),
    ]


class xdo_search_t(Structure):
    """
    The window search query structure.

    :see: xdo_search_windows
    """

    _fields_ = [
        # const char *title; pattern to test against a window title
        ("title", c_char_p),
        # const char *winclass; pattern to test against a window class
        ("winclass", c_char_p),
        # const char *winclassname; pattern to test against a window class
        ("winclassname", c_char_p),
        # const char *winname; pattern to test against a window name
        ("winname", c_char_p),
        # int pid; window pid (From window atom _NET_WM_PID)
        ("pid", c_int),
        # long max_depth; depth of search. 1 means only toplevel windows
        ("max_depth", c_long),
        # int only_visible; boolean; set true to search only visible windows
        ("only_visible", c_int),
        # int screen; what screen to search, if any. If none given,
        #             search all screens
        ("screen", c_int),
        # int steam_game; steam game id (From window atom STEAM_GAME)
        ("steam_game", c_int),
        # Should the tests be 'and' or 'or' ? If 'and', any failure
        # will skip the window. If 'or', any success will keep the window
        # in search results.
        # enum { SEARCH_ANY, SEARCH_ALL } require;
        ("require", c_int),
        # bitmask of things you are searching for, such as SEARCH_NAME, etc.
        # :see: SEARCH_NAME, SEARCH_CLASS, SEARCH_PID, SEARCH_CLASSNAME, etc
        # unsigned int searchmask;
        ("searchmask", c_uint),
        # What desktop to search, if any. If none given, search
        # all screens.
        # long desktop;
        ("desktop", c_long),
        # How many results to return? If 0, return all.
        # unsigned int limit;
        ("limit", c_uint),
    ]


# From X11/Xdefs.h
# typedef unsigned long Atom;
Atom = atom_t = c_ulong

# ============================================================================
# xdo_t* xdo_new(const char *display);
myxdo.xdo_new.argtypes = (c_char_p,)
myxdo.xdo_new.restype = POINTER(xdo_t)
myxdo.xdo_new.__doc__ = """\
Create a new xdo_t instance.

:param display: the string display name, such as ":0". If null, uses the
environment variable DISPLAY just like XOpenDisplay(NULL).

:return: Pointer to a new xdo_t or NULL on failure
"""

# ============================================================================
# xdo_t* xdo_new_with_opened_display(Display *xdpy, const char *display,
#                                    int close_display_when_freed);
myxdo.xdo_new_with_opened_display.__doc__ = """\
Create a new xdo_t instance with an existing X11 Display instance.

:param xdpy: the Display pointer given by a previous XOpenDisplay()
:param display: the string display name
:param close_display_when_freed: If true, we will close the display when
    xdo_free is called. Otherwise, we leave it open.
"""

# ============================================================================
# void xdo_free(xdo_t *xdo);
myxdo.xdo_free.argtypes = (POINTER(xdo_t),)
myxdo.xdo_free.__doc__ = """\
Free and destroy an xdo_t instance.

If close_display_when_freed is set, then we will also close the Display.
"""

# ============================================================================
# int xdo_search_windows(const xdo_t *xdo, const xdo_search_t *search,
#                       Window **windowlist_ret, unsigned int *nwindows_ret);
myxdo.xdo_search_windows.argtypes = (
    POINTER(xdo_t),
    POINTER(xdo_search_t),
    POINTER(POINTER(window_t)),
    POINTER(c_uint),
)
myxdo.xdo_search_windows.restype = c_int
myxdo.xdo_search_windows.errcheck = _errcheck_cb  # type: ignore
myxdo.xdo_search_windows.__doc__ = """\
Search for windows.

:param search: the search query.
:param windowlist_ret: the list of matching windows to return
:param nwindows_ret: the number of windows (length of windowlist_ret)
:see: xdo_search_t
"""


def search_windows(
    xdo: xdo_t,
    winname: Optional[str] = None,
    winclass: Optional[str] = None,
    winclassname: Optional[str] = None,
    pid: Optional[int] = None,
    steam_game: Optional[int] = None,
    only_visible: bool = False,
    screen: Optional[int] = None,
    require: bool = False,
    searchmask: int = 0,
    desktop: Optional[int] = None,
    limit: int = 0,
    max_depth: int = -1,
) -> List[window_t]:
    """
    Search for windows.

    :param winname:
        Regexp to be matched against window name
    :param winclass:
        Regexp to be matched against window class
    :param winclassname:
        Regexp to be matched against window class name
    :param pid:
        Only return windows from this PID
    :param only_visible:
        If True, only return visible windows
    :param screen:
        Search only windows on this screen
    :param require:
        If True, will match ALL conditions. Otherwise, windows matching
        ANY condition will be returned.
    :param searchmask:
        Search mask, for advanced usage. Leave this alone if you
        don't kwnow what you are doing.
    :param limit:
        Maximum number of windows to list. Zero means no limit.
    :param max_depth:
        Maximum depth to return. Defaults to -1, meaning "no limit".
    :return:
        A list of window ids matching query.
    """
    # pylint: disable=attribute-defined-outside-init
    windowlist_ret = pointer(window_t(0))
    nwindows_ret = c_uint(0)

    search = xdo_search_t(searchmask=searchmask)
    search.searchmask = searchmask

    if winname is not None:
        search.winname = winname.encode("utf-8")
        search.searchmask |= SEARCH_NAME

    if winclass is not None:
        search.winclass = winclass.encode("utf-8")
        search.searchmask |= SEARCH_CLASS

    if winclassname is not None:
        search.winclassname = winclassname.encode("utf-8")
        search.searchmask |= SEARCH_CLASSNAME

    if pid is not None:
        search.pid = pid
        search.searchmask |= SEARCH_PID

    if steam_game is not None:
        search.steam_game = steam_game
        search.searchmask |= SEARCH_STEAM

    if only_visible:
        search.only_visible = True
        search.searchmask |= SEARCH_ONLYVISIBLE

    if screen is not None:
        search.screen = screen
        search.searchmask |= SEARCH_SCREEN

    if desktop is not None:
        search.screen = desktop
        search.searchmask |= SEARCH_DESKTOP

    if require:
        search.require = 0  # SEARCH_ALL
    else:
        search.require = 1  # SEARCH_ANY

    search.limit = limit
    search.max_depth = max_depth

    myxdo.xdo_search_windows(xdo, search, byref(windowlist_ret), byref(nwindows_ret))

    return [windowlist_ret[i] for i in range(nwindows_ret.value)]


def watch_focus(
    window_ids: Iterable[int],
    focus_in_cb: Callable[[display.event.FocusIn], None],
    focus_out_cb: Callable[[display.event.FocusOut], None],
) -> int:
    """
    Watches for focus changes on all windows in `window_ids`, and executes the
    corresponding callback with the specified event.
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
            logger.error("Bad window ID: 0x{:x}".format(err.resource_id.id))
            return -1
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
            return int(evt.window.id)
        if isinstance(evt, display.event.Focus):
            if evt.mode not in (X.NotifyNormal, X.NotifyWhileGrabbed):
                continue
            if evt.type == X.FocusIn and focused != evt.window:
                focus_in_cb(evt)
                focused = evt.window
            if (
                evt.type == X.FocusOut
                and focused == evt.window
                and evt.detail != X.NotifyInferior
            ):
                focus_out_cb(evt)
                focused = X.NONE

    return 0


def pgrep(pattern: str, match_full: bool = False) -> List[Process]:
    """
    Works like the pgrep command. Searches /proc for a matching process.

    :param pattern: a regular expression to match against
    :param match_full: if True, match against ``/proc/<pid>/cmdline`` instead of
                       ``/proc/<pid>/comm`` (which is limited to 15 characters)
    :return: a list of matching processes
    """
    import re

    regex = re.compile(pattern)
    own_pid = str(os.getpid())

    procs = list()
    for proc in find_processes():
        if proc.pid == own_pid or not proc.cmdline:
            continue

        if match_full:
            for val in proc.cmdline:
                if regex.search(val) is not None:
                    # found match
                    procs.append(proc)
                    break
        else:
            # only match against argv[0]
            if regex.search(proc.cmdline[0]) is not None:
                # found match
                procs.append(proc)

    return procs


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

    def focus_in(evt: display.event.FocusIn) -> None:
        """
        Prints message about window that got focus
        """
        cls = evt.window.get_wm_class() or ("", "")
        print(
            'Got  focus on window 0x{:07x} ({:s}) "{:s}"'.format(
                evt.window.id, DETAIL_LUT[evt.detail], cls[1]
            )
        )

    def focus_out(evt: display.event.FocusOut) -> None:
        """
        Prints message about window that lost focus
        """
        cls = evt.window.get_wm_class() or ("", "")
        print(
            'Lost focus on window 0x{:07x} ({:s}) "{:s}"'.format(
                evt.window.id, DETAIL_LUT[evt.detail], cls[1]
            )
        )

    sys.exit(watch_focus([int(arg, 0) for arg in sys.argv[1:]], focus_in, focus_out))
