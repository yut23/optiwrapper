/* xdo search implementation
 *
 * Lets you search windows by a query
 */

#ifndef _XOPEN_SOURCE
#define _XOPEN_SOURCE 500
#endif /* _XOPEN_SOURCE */

#include "myxdo.h"
#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xlibint.h>
#include <X11/Xresource.h>
#include <X11/Xutil.h>
#include <X11/extensions/XTest.h>
#include <regex.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int compile_re(const char *pattern, regex_t *re);
static int check_window_match(const xdo_t *xdo, Window wid,
                              const xdo_search_t *search);
static int _xdo_match_window_class(const xdo_t *xdo, Window window,
                                   regex_t *re);
static int _xdo_match_window_classname(const xdo_t *xdo, Window window,
                                       regex_t *re);
static int _xdo_match_window_name(const xdo_t *xdo, Window window, regex_t *re);
static int _xdo_match_window_pid(const xdo_t *xdo, Window window, int pid);
static int _xdo_match_window_steam_game(const xdo_t *xdo, Window window,
                                        int steam_game);
static int _xdo_is_window_visible(const xdo_t *xdo, Window wid);
static void find_matching_windows(const xdo_t *xdo, Window window,
                                  const xdo_search_t *search,
                                  Window **windowlist_ret,
                                  unsigned int *nwindows_ret,
                                  unsigned int *windowlist_size,
                                  int current_depth);

static Atom atom_NET_WM_PID = -1;
static Atom atom_STEAM_GAME = -1;

int _is_success(const char *funcname, int code, const xdo_t *xdo) {
  /* Nonzero is failure. */
  if (code != 0 && !xdo->quiet)
    fprintf(stderr, "%s failed (code=%d)\n", funcname, code);
  return code;
}

void _xdo_debug(const xdo_t *xdo, const char *format, ...) {
  va_list args;

  va_start(args, format);
  if (xdo->debug) {
    vfprintf(stderr, format, args);
    fprintf(stderr, "\n");
  }
  va_end(args);
} /* _xdo_debug */

/* Used for printing things conditionally based on xdo->quiet */
void _xdo_eprintf(const xdo_t *xdo, int hushable, const char *format, ...) {
  va_list args;

  if (xdo->quiet == True && hushable) {
    return;
  }

  va_start(args, format);
  vfprintf(stderr, format, args);
  fprintf(stderr, "\n");
  va_end(args);
} /* _xdo_eprintf */

static int error_handler(Display *dpy, XErrorEvent *ev) {
  if (ev->error_code == BadWindow) {
    /* window has disappeared, ignore it */
    return 0;
  }
  return _XDefaultError(dpy, ev);
}

xdo_t *xdo_new(const char *display_name) {
  Display *xdpy;
  xdo_t *xdo = NULL;

  if ((xdpy = XOpenDisplay(display_name)) == NULL) {
    /* Can't use _xdo_eprintf yet ... */
    fprintf(stderr, "Error: Can't open display: %s\n", display_name);
    return NULL;
  }

  xdo = malloc(sizeof(xdo_t));
  if (xdo == NULL) {
    perror("xdo_new: couldn't allocate xdo_t");
    return NULL;
  }
  memset(xdo, 0, sizeof(xdo_t)); // NOLINT

  xdo->xdpy = xdpy;
  xdo->close_display_when_freed = 1;

  /*if (display == NULL) {
    display = "unknown";
  }*/

  if (getenv("XDO_QUIET")) {
    xdo->quiet = True;
  }

  return xdo;
}

void xdo_free(xdo_t *xdo) {
  if (xdo == NULL)
    return;

  if (xdo->display_name)
    free(xdo->display_name);
  if (xdo->xdpy && xdo->close_display_when_freed)
    XCloseDisplay(xdo->xdpy);

  free(xdo);
}

/* Arbitrary window property retrieval
 * slightly modified version from xprop.c from Xorg */
unsigned char *xdo_get_window_property_by_atom(const xdo_t *xdo, Window window,
                                               Atom atom, long *nitems,
                                               Atom *type, int *size) {
  Atom actual_type;
  int actual_format;
  unsigned long _nitems;
  /*unsigned long nbytes;*/
  unsigned long bytes_after; /* unused */
  unsigned char *prop;
  int status;

  status = XGetWindowProperty(xdo->xdpy, window, atom, 0, (~0L), False,
                              AnyPropertyType, &actual_type, &actual_format,
                              &_nitems, &bytes_after, &prop);
  if (status == BadWindow) {
    fprintf(stderr, "window id # 0x%lx does not exists!", window);
    return NULL;
  }
  if (status != Success) {
    fprintf(stderr, "XGetWindowProperty failed!");
    return NULL;
  }

  /*
   *if (actual_format == 32)
   *  nbytes = sizeof(long);
   *else if (actual_format == 16)
   *  nbytes = sizeof(short);
   *else if (actual_format == 8)
   *  nbytes = 1;
   *else if (actual_format == 0)
   *  nbytes = 0;
   */

  if (nitems != NULL) {
    *nitems = _nitems;
  }

  if (type != NULL) {
    *type = actual_type;
  }

  if (size != NULL) {
    *size = actual_format;
  }
  return prop;
}

int _xdo_ewmh_is_supported(const xdo_t *xdo, const char *feature) {
  Atom type = 0;
  long nitems = 0L;
  int size = 0;
  Atom *results = NULL;
  long i = 0;

  Window root;
  Atom request;
  Atom feature_atom;

  request = XInternAtom(xdo->xdpy, "_NET_SUPPORTED", False);
  feature_atom = XInternAtom(xdo->xdpy, feature, False);
  root = XDefaultRootWindow(xdo->xdpy);

  results = (Atom *)xdo_get_window_property_by_atom(xdo, root, request, &nitems,
                                                    &type, &size);
  for (i = 0L; i < nitems; i++) {
    if (results[i] == feature_atom) {
      XFree(results);
      return True;
    }
  }
  XFree(results);

  return False;
}

int xdo_get_desktop_for_window(const xdo_t *xdo, Window wid, long *desktop) {
  Atom type;
  int size = 0;
  long nitems = 0;
  unsigned char *data;
  Atom request;
  XErrorHandler handler;

  if (_xdo_ewmh_is_supported(xdo, "_NET_WM_DESKTOP") == False) {
    fprintf(stderr, "Your windowmanager claims not to support _NET_WM_DESKTOP, "
                    "so the attempt to query a window's desktop location was "
                    "aborted.\n");
    return XDO_ERROR;
  }

  request = XInternAtom(xdo->xdpy, "_NET_WM_DESKTOP", False);

  handler = XSetErrorHandler(error_handler);
  data =
      xdo_get_window_property_by_atom(xdo, wid, request, &nitems, &type, &size);
  XSetErrorHandler(handler);

  if (nitems > 0) {
    *desktop = *((long *)data);
  } else {
    *desktop = -1;
  }
  XFree(data);

  return _is_success("XGetWindowProperty[_NET_WM_DESKTOP]", *desktop == -1,
                     xdo);
}

int xdo_search_windows(const xdo_t *xdo, const xdo_search_t *search,
                       Window **windowlist_ret, unsigned int *nwindows_ret) {

  XErrorHandler handler;
  unsigned int windowlist_size = 100;
  *nwindows_ret = 0;
  *windowlist_ret = calloc(sizeof(Window), windowlist_size);

  handler = XSetErrorHandler(error_handler);
  /* TODO(sissel): Support multiple screens */
  if (search->searchmask & SEARCH_SCREEN) {
    Window root = RootWindow(xdo->xdpy, search->screen);
    if (check_window_match(xdo, root, search)) {
      (*windowlist_ret)[*nwindows_ret] = root;
      (*nwindows_ret)++;
      /* Don't have to check for size bounds here because
       * we start with array size 100 */
    }

    /* Start with depth=1 since we already covered the root windows */
    find_matching_windows(xdo, root, search, windowlist_ret, nwindows_ret,
                          &windowlist_size, 1);
  } else {
    const int screencount = ScreenCount(xdo->xdpy);
    for (int i = 0; i < screencount; i++) {
      Window root = RootWindow(xdo->xdpy, i);
      if (check_window_match(xdo, root, search)) {
        (*windowlist_ret)[*nwindows_ret] = root;
        (*nwindows_ret)++;
        /* Don't have to check for size bounds here because
         * we start with array size 100 */
      }

      /* Start with depth=1 since we already covered the root windows */
      find_matching_windows(xdo, root, search, windowlist_ret, nwindows_ret,
                            &windowlist_size, 1);
    }
  }
  XSetErrorHandler(handler);

  // printf("Window count: %d\n", (int)ncandidate_windows);
  // printf("Search:\n");
  // printf("onlyvisible: %d\n", search->only_visible);
  // printf("pid: %lu\n", search->pid);
  // printf("name: %s\n", search->winname);
  // printf("class: %s\n", search->winclass);
  // printf("classname: %s\n", search->winclassname);
  // printf("//Search\n");

  return XDO_SUCCESS;
} /* int xdo_search_windows */

static int _xdo_match_window_name(const xdo_t *xdo, Window window,
                                  regex_t *re) {
  /* historically in xdo, 'match_name' matched the classhint 'name' which we
   * match in _xdo_match_window_classname. But really, most of the time 'name'
   * refers to the window manager name for the window, which is displayed in
   * the titlebar */
  int count = 0;
  char **list = NULL;
  XTextProperty tp;

  if (XGetWMName(xdo->xdpy, window, &tp) == 0)
    return False;

  if (tp.nitems > 0) {
    // XmbTextPropertyToTextList(xdo->xdpy, &tp, &list, &count);
    Xutf8TextPropertyToTextList(xdo->xdpy, &tp, &list, &count);
    for (int i = 0; i < count; i++) {
      if (regexec(re, list[i], 0, NULL, 0) == 0) {
        XFreeStringList(list);
        XFree(tp.value);
        return True;
      }
    }
  } else {
    /* Treat windows with no names as empty strings */
    if (regexec(re, "", 0, NULL, 0) == 0) {
      XFreeStringList(list);
      XFree(tp.value);
      return True;
    }
  }
  XFreeStringList(list);
  XFree(tp.value);
  return False;
} /* int _xdo_match_window_name */

static int _xdo_match_window_class(const xdo_t *xdo, Window window,
                                   regex_t *re) {
  XClassHint classhint;

  if (XGetClassHint(xdo->xdpy, window, &classhint)) {
    // printf("%d: class %s\n", window, classhint.res_class);
    if ((classhint.res_class) &&
        (regexec(re, classhint.res_class, 0, NULL, 0) == 0)) {
      XFree(classhint.res_name);
      XFree(classhint.res_class);
      return True;
    }
    XFree(classhint.res_name);
    XFree(classhint.res_class);
  } else {
    /* Treat windows with no class as empty strings */
    if (regexec(re, "", 0, NULL, 0) == 0) {
      return True;
    }
  }
  return False;
} /* int _xdo_match_window_class */

static int _xdo_match_window_classname(const xdo_t *xdo, Window window,
                                       regex_t *re) {
  XClassHint classhint;

  if (XGetClassHint(xdo->xdpy, window, &classhint)) {
    if ((classhint.res_name) &&
        (regexec(re, classhint.res_name, 0, NULL, 0) == 0)) {
      XFree(classhint.res_name);
      XFree(classhint.res_class);
      return True;
    }
    XFree(classhint.res_name);
    XFree(classhint.res_class);
  } else {
    /* Treat windows with no class name as empty strings */
    if (regexec(re, "", 0, NULL, 0) == 0) {
      return True;
    }
  }
  return False;
} /* int _xdo_match_window_classname */

int xdo_get_pid_window(const xdo_t *xdo, Window window) {
  Atom type;
  int size = 0;
  long nitems = 0;
  unsigned char *data;
  int window_pid = 0;

  if (atom_NET_WM_PID == (Atom)-1) {
    atom_NET_WM_PID = XInternAtom(xdo->xdpy, "_NET_WM_PID", False);
  }

  data = xdo_get_window_property_by_atom(xdo, window, atom_NET_WM_PID, &nitems,
                                         &type, &size);

  if (nitems > 0) {
    /* The data itself is unsigned long, but everyone uses int as pid values */
    window_pid = (int)*((unsigned long *)data);
  }
  XFree(data);

  return window_pid;
}

static int _xdo_match_window_pid(const xdo_t *xdo, Window window,
                                 const int pid) {
  int window_pid;

  window_pid = xdo_get_pid_window(xdo, window);
  if (pid == window_pid) {
    return True;
  } else {
    return False;
  }
} /* int _xdo_match_window_pid */

static int _xdo_match_window_steam_game(const xdo_t *xdo, Window window,
                                        const int steam_game) {
  Atom type;
  int size = 0;
  long nitems = 0;
  unsigned char *data;
  int window_steam_game = 0;

  if (atom_STEAM_GAME == (Atom)-1) {
    atom_STEAM_GAME = XInternAtom(xdo->xdpy, "STEAM_GAME", False);
  }

  data = xdo_get_window_property_by_atom(xdo, window, atom_NET_WM_PID, &nitems,
                                         &type, &size);

  if (nitems > 0) {
    /* The data itself is unsigned long, but everyone uses int as pid values */
    window_steam_game = (int)*((unsigned long *)data);
  }
  XFree(data);

  if (steam_game == window_steam_game) {
    return True;
  } else {
    return False;
  }
} /* int _xdo_match_window_steam_game */

static int compile_re(const char *pattern, regex_t *re) {
  int ret;
  if (pattern == NULL) {
    regcomp(re, "^$", REG_EXTENDED | REG_ICASE);
    return True;
  }

  ret = regcomp(re, pattern, REG_EXTENDED | REG_ICASE);
  if (ret != 0) {
    fprintf(stderr, "Failed to compile regex (return code %d): '%s'\n", ret,
            pattern);
    return False;
  }
  return True;
} /* int compile_re */

static int _xdo_is_window_visible(const xdo_t *xdo, Window wid) {
  XWindowAttributes wattr;
  if (XGetWindowAttributes(xdo->xdpy, wid, &wattr) == 0)
    return False;
  if (wattr.map_state != IsViewable)
    return False;

  return True;
} /* int _xdo_is_window_visible */

static int check_window_match(const xdo_t *xdo, Window wid,
                              const xdo_search_t *search) {
  regex_t class_re;
  regex_t classname_re;
  regex_t name_re;

  if (!compile_re(search->winclass, &class_re) ||
      !compile_re(search->winclassname, &classname_re) ||
      !compile_re(search->winname, &name_re)) {

    regfree(&class_re);
    regfree(&classname_re);
    regfree(&name_re);

    return False;
  }

  /* Set this to 1 for dev debugging */
  static const int debug = 0;

  int visible_ok, pid_ok, name_ok, class_ok, classname_ok, desktop_ok,
      steam_game_ok;
  int visible_want, pid_want, name_want, class_want, classname_want,
      desktop_want, steam_game_want;

  visible_ok = pid_ok = name_ok = class_ok = classname_ok = desktop_ok =
      steam_game_ok = True;
  //(search->require == SEARCH_ANY ? False : True);

  desktop_want = search->searchmask & SEARCH_DESKTOP;
  visible_want = search->searchmask & SEARCH_ONLYVISIBLE;
  pid_want = search->searchmask & SEARCH_PID;
  name_want = search->searchmask & SEARCH_NAME;
  class_want = search->searchmask & SEARCH_CLASS;
  classname_want = search->searchmask & SEARCH_CLASSNAME;
  steam_game_want = search->searchmask & SEARCH_STEAM;

  do {
    if (desktop_want) {
      long desktop = -1;

      /* We're modifying xdo here, but since we restore it, we're still
       * obeying the "const" contract. */
      int old_quiet = xdo->quiet;
      xdo_t *xdo2 = (xdo_t *)xdo;
      xdo2->quiet = 1;
      int ret = xdo_get_desktop_for_window(xdo2, wid, &desktop);
      xdo2->quiet = old_quiet;

      /* Desktop matched if we support desktop queries *and* the desktop is
       * equal */
      desktop_ok = (ret == XDO_SUCCESS && desktop == search->desktop);
    }

    /* Visibility is a hard condition, fail always if we wanted
     * only visible windows and this one isn't */
    if (visible_want && !_xdo_is_window_visible(xdo, wid)) {
      /*if (debug)
        fprintf(stderr, "skip %lx visible\n", wid);*/
      visible_ok = False;
      break;
    }

    if (pid_want && !_xdo_match_window_pid(xdo, wid, search->pid)) {
      if (debug)
        fprintf(stderr, "skip %lx pid\n", wid);
      pid_ok = False;
    }

    if (steam_game_want &&
        !_xdo_match_window_steam_game(xdo, wid, search->steam_game)) {
      if (debug)
        fprintf(stderr, "skip %lx steam_game\n", wid);
      steam_game_ok = False;
    }

    if (name_want && !_xdo_match_window_name(xdo, wid, &name_re)) {
      /*if (debug)
        fprintf(stderr, "skip %lx winname\n", wid);*/
      name_ok = False;
    }

    if (class_want && !_xdo_match_window_class(xdo, wid, &class_re)) {
      if (debug)
        fprintf(stderr, "skip %lx winclass\n", wid);
      class_ok = False;
    }

    if (classname_want &&
        !_xdo_match_window_classname(xdo, wid, &classname_re)) {
      /*if (debug)
        fprintf(stderr, "skip %lx winclassname\n", wid);*/
      classname_ok = False;
    }
  } while (0);

  regfree(&class_re);
  regfree(&classname_re);
  regfree(&name_re);

  if (debug) {
    if (visible_ok &&
        ((classname_want && classname_ok) || (name_want && name_ok))) {
      fprintf(stderr,
              "win: %lx, pid:%d, name:%d, class:%d, classname:%d, "
              "visible:%d, steam:%d\n",
              wid, pid_ok, name_ok, class_ok, classname_ok, visible_ok,
              steam_game_ok);
    }
  }

  switch (search->require) {
  case SEARCH_ALL:
    return visible_ok && pid_ok && name_ok && class_ok && classname_ok &&
           desktop_ok && steam_game_ok;
    break;
  case SEARCH_ANY:
    return visible_ok &&
           ((pid_want && pid_ok) || (name_want && name_ok) ||
            (class_want && class_ok) || (classname_want && classname_ok) ||
            (steam_game_want && steam_game_ok)) &&
           desktop_ok;
    break;
  }

  fprintf(stderr,
          "Unexpected code reached. search->require is not valid? (%d); "
          "this may be a bug?\n",
          search->require);
  return False;
} /* int check_window_match */

static void find_matching_windows(const xdo_t *xdo, Window window,
                                  const xdo_search_t *search,
                                  Window **windowlist_ret,
                                  unsigned int *nwindows_ret,
                                  unsigned int *windowlist_size,
                                  int current_depth) {
  /* Query for children of 'wid'. For each child, check match.
   * We want to do a breadth-first search.
   *
   * If match, add to list.
   * If over limit, break.
   * Recurse.
   */

  Window dummy;
  Window *children;
  unsigned int i, nchildren;

  /* Break early, if we have enough windows already. */
  if (search->limit > 0 && *nwindows_ret >= search->limit) {
    return;
  }

  /* Break if too deep */
  if (search->max_depth != -1 && current_depth > search->max_depth) {
    return;
  }

  /* Break if XQueryTree fails.
   * TODO(sissel): report an error? */
  Status success =
      XQueryTree(xdo->xdpy, window, &dummy, &dummy, &children, &nchildren);

  if (!success) {
    return;
  }

  /* Breadth first, check all children for matches */
  for (i = 0; i < nchildren; i++) {
    Window child = children[i];
    if (!check_window_match(xdo, child, search))
      continue;

    (*windowlist_ret)[*nwindows_ret] = child;
    (*nwindows_ret)++;

    if (search->limit > 0 && *nwindows_ret >= search->limit) {
      /* Limit hit, break early. */
      break;
    }

    if (*windowlist_size == *nwindows_ret) {
      *windowlist_size *= 2;
      *windowlist_ret =
          realloc(*windowlist_ret, *windowlist_size * sizeof(Window));
    }
  } /* for (i in children) ... */

  /* Now check children-children */
  if (search->max_depth == -1 || (current_depth + 1) <= search->max_depth) {
    for (i = 0; i < nchildren; i++) {
      find_matching_windows(xdo, children[i], search, windowlist_ret,
                            nwindows_ret, windowlist_size, current_depth + 1);
    }
  } /* recurse on children if not at max depth */

  if (children != NULL)
    XFree(children);
} /* void find_matching_windows */
