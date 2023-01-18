/**
 * @file myxdo.h
 */
#ifndef _MYXDO_H_
#define _MYXDO_H_

#ifndef __USE_XOPEN
#define __USE_XOPEN
#endif /* __USE_XOPEN */

#include <X11/X.h>
#include <X11/Xlib.h>
#include <sys/types.h>
#include <unistd.h>

/**
 * @mainpage
 *
 * libxdo helps you send fake mouse and keyboard input, search for windows,
 * perform various window management tasks such as desktop changes, window
 * movement, etc.
 *
 * For examples on libxdo usage, the xdotool source code is a good reference.
 *
 * @see xdo.h
 * @see xdo_new
 */

/**
 * The main context.
 */
typedef struct xdo {

  /** The Display for Xlib */
  Display *xdpy;

  /** The display name, if any. NULL if not specified. */
  char *display_name;

  /** Should we close the display when calling xdo_free? */
  int close_display_when_freed;

  /** Be extra quiet? (omits some error/message output) */
  int quiet;

  /** Enable debug output? */
  int debug;

} xdo_t;

/**
 * Search only window class.
 * @see xdo_search_windows
 */
#define SEARCH_CLASS (1UL << 0)

/**
 * Search only window name.
 * @see xdo_search_windows
 */
#define SEARCH_NAME (1UL << 1)

/**
 * Search only window pid.
 * @see xdo_search_windows
 */
#define SEARCH_PID (1UL << 2)

/**
 * Search only visible windows.
 * @see xdo_search_windows
 */
#define SEARCH_ONLYVISIBLE (1UL << 3)

/**
 * Search only a specific screen.
 * @see xdo_search.screen
 * @see xdo_search_windows
 */
#define SEARCH_SCREEN (1UL << 4)

/**
 * Search only window class name.
 * @see xdo_search
 */
#define SEARCH_CLASSNAME (1UL << 5)

/**
 * Search a specific desktop
 * @see xdo_search.screen
 * @see xdo_search_windows
 */
#define SEARCH_DESKTOP (1UL << 6)

/**
 * Search a specific STEAM_GAME ID
 * @see xdo_search.screen
 * @see xdo_search_windows
 */
#define SEARCH_STEAM (1UL << 7)

/**
 * The window search query structure.
 *
 * @see xdo_search_windows
 */
typedef struct xdo_search {
  const char *winclass;     /** pattern to test against a window class */
  const char *winclassname; /** pattern to test against a window class */
  const char *winname;      /** pattern to test against a window name */
  int pid;                  /** window pid (From window atom _NET_WM_PID) */
  long max_depth;   /** depth of search. 1 means only toplevel windows */
  int only_visible; /** boolean; set true to search only visible windows */
  int screen;       /** what screen to search, if any. If none given, search
                       all screens */
  int steam_game;   /** steam game id (From window atom STEAM_GAME) */

  /** Should the tests be 'and' or 'or' ? If 'and', any failure will skip the
   * window. If 'or', any success will keep the window in search results. */
  enum { SEARCH_ANY, SEARCH_ALL } require;

  /** bitmask of things you are searching for, such as SEARCH_NAME, etc.
   * @see SEARCH_NAME, SEARCH_CLASS, SEARCH_PID, SEARCH_CLASSNAME, etc
   */
  unsigned int searchmask;

  /** What desktop to search, if any. If none given, search all screens. */
  long desktop;

  /** How many results to return? If 0, return all. */
  unsigned int limit;
} xdo_search_t;

#define XDO_ERROR 1
#define XDO_SUCCESS 0

/**
 * Create a new xdo_t instance.
 *
 * @param display the string display name, such as ":0". If null, uses the
 * environment variable DISPLAY just like XOpenDisplay(NULL).
 *
 * @return Pointer to a new xdo_t or NULL on failure
 */
xdo_t *xdo_new(const char *display);

/**
 * Free and destroy an xdo_t instance.
 *
 * If close_display_when_freed is set, then we will also close the Display.
 */
void xdo_free(xdo_t *xdo);

/**
 * Get the desktop a window is on.
 * Uses _NET_WM_DESKTOP of the EWMH spec.
 *
 * If your desktop does not support _NET_WM_DESKTOP, then '*desktop' remains
 * unmodified.
 *
 * @param wid the window to query
 * @param deskto pointer to long where the desktop of the window is stored
 */
int xdo_get_desktop_for_window(const xdo_t *xdo, Window wid, long *desktop);

/**
 * Search for windows.
 *
 * @param search the search query.
 * @param windowlist_ret the list of matching windows to return
 * @param nwindows_ret the number of windows (length of windowlist_ret)
 * @see xdo_search_t
 */
int xdo_search_windows(const xdo_t *xdo, const xdo_search_t *search,
                       Window **windowlist_ret, unsigned int *nwindows_ret);

/**
 * Get a window ID by clicking on it. This function blocks until a selection
 * is made.
 *
 * @param window_ret Pointer to Window where the selected window is stored.
 */
int xdo_select_window_with_click(const xdo_t *xdo, Window *window_ret);
#endif /* ifndef _MYXDO_H_ */
