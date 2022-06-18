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
from typing import List, Optional

_myxdo = CDLL("/home/eric/Games/wrapper/myxdo.so")

XDO_ERROR = 1
XDO_SUCCESS = 0

# Search only window class.
SEARCH_CLASS = 1 << 0

# Search only window name.
SEARCH_NAME = 1 << 1

# Search only window pid.
SEARCH_PID = 1 << 2

# Search only visible windows.
SEARCH_ONLYVISIBLE = 1 << 3

# Search only a specific screen.
SEARCH_SCREEN = 1 << 4

# Search only window class name.
SEARCH_CLASSNAME = 1 << 5

# Search a specific desktop
SEARCH_DESKTOP = 1 << 6

# Search a specific STEAM_GAME id
SEARCH_STEAM = 1 << 7

SEARCH_ANY = 0
SEARCH_ALL = 1

window_t = c_ulong


class XdoException(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


def _errcheck_cb(result, func, arguments):
    """
    Error checker for functions returning an integer indicating
    success (0) / failure (1).

    Raises a XdoException in case of error, otherwise just returns `None`
    (returning the original code, 0, would be useless anyways..)
    """

    if result != 0:
        raise XdoException(
            result, "Function {0} returned error code {1}".format(func.__name__, result)
        )


class xdo_t(Structure):
    """The main context"""

    # pylint: disable=too-few-public-methods

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

    # pylint: disable=too-few-public-methods, too-many-instance-attributes

    _fields_ = [
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
_myxdo.xdo_new.argtypes = (c_char_p,)
_myxdo.xdo_new.restype = POINTER(xdo_t)
_myxdo.xdo_new.__doc__ = """\
Create a new xdo_t instance.

:param display: the string display name, such as ":0". If null, uses the
environment variable DISPLAY just like XOpenDisplay(NULL).

:return: Pointer to a new xdo_t or NULL on failure
"""
xdo_new = _myxdo.xdo_new

# ============================================================================
# void xdo_free(xdo_t *xdo);
_myxdo.xdo_free.argtypes = (POINTER(xdo_t),)
_myxdo.xdo_free.__doc__ = """\
Free and destroy an xdo_t instance and close the Display.
"""
xdo_free = _myxdo.xdo_free

# ============================================================================
# int xdo_search_windows(const xdo_t *xdo, const xdo_search_t *search,
#                       Window **windowlist_ret, unsigned int *nwindows_ret);
_myxdo.xdo_search_windows.argtypes = (
    POINTER(xdo_t),
    POINTER(xdo_search_t),
    POINTER(POINTER(window_t)),
    POINTER(c_uint),
)
_myxdo.xdo_search_windows.restype = c_int
_myxdo.xdo_search_windows.errcheck = _errcheck_cb  # type: ignore
_myxdo.xdo_search_windows.__doc__ = """\
Search for windows.

:param search: the search query.
:param windowlist_ret: the list of matching windows to return
:param nwindows_ret: the number of windows (length of windowlist_ret)
:see: xdo_search_t
"""

# ============================================================================
# int test_re(const char *pattern);
_myxdo.test_re.argtypes = (c_char_p,)
_myxdo.test_re.restype = c_int


def xdo_search_windows(
    xdo: Optional[xdo_t] = None,
    winname: Optional[str] = None,
    winclass: Optional[str] = None,
    winclassname: Optional[str] = None,
    pid: Optional[int] = None,
    steam_game: Optional[int] = None,
    only_visible: bool = True,
    screen: Optional[int] = None,
    require_all: bool = False,
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
    :param require_all:
        If True, will match ALL conditions. Otherwise, windows matching
        ANY condition will be returned.
    :param searchmask:
        Search mask, for advanced usage. Leave this alone if you
        don't know what you are doing.
    :param limit:
        Maximum number of windows to list. Zero means no limit.
    :param max_depth:
        Maximum depth to search. Defaults to -1, meaning "no limit".
    :return:
        A list of window ids matching query.
    """
    # pylint: disable=attribute-defined-outside-init, too-many-arguments, too-many-locals
    windowlist_ret = pointer(window_t(0))
    nwindows_ret = c_uint(0)

    search = xdo_search_t(searchmask=searchmask)
    search.searchmask = searchmask

    if winname is not None:
        if r"\d" in winname:
            raise ValueError(r"Posix EREs don't support \d, use [0-9] instead")
        search.winname = winname.encode("utf-8")
        if not _myxdo.test_re(search.winname):
            raise ValueError("Invalid regular expression (see error message above)")
        search.searchmask |= SEARCH_NAME

    if winclass is not None:
        if r"\d" in winclass:
            raise ValueError(r"Posix EREs don't support \d, use [0-9] instead")
        search.winclass = winclass.encode("utf-8")
        if not _myxdo.test_re(search.winclass):
            raise ValueError("Invalid regular expression (see error message above)")
        search.searchmask |= SEARCH_CLASS

    if winclassname is not None:
        if r"\d" in winclassname:
            raise ValueError(r"Posix EREs don't support \d, use [0-9] instead")
        search.winclassname = winclassname.encode("utf-8")
        if not _myxdo.test_re(search.winclassname):
            raise ValueError("Invalid regular expression (see error message above)")
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

    if require_all:
        search.require = SEARCH_ALL
    else:
        search.require = SEARCH_ANY

    search.limit = limit
    search.max_depth = max_depth

    make_xdo = xdo is None
    if make_xdo:
        xdo = xdo_new(None)
    _myxdo.xdo_search_windows(xdo, search, byref(windowlist_ret), byref(nwindows_ret))
    if make_xdo:
        xdo_free(xdo)

    return [windowlist_ret[i] for i in range(nwindows_ret.value)]
