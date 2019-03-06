#include <assert.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xdo.h>

#include <X11/X.h>
#include <X11/Xutil.h>

const char *usage = "Usage: %s window ids ...\n";

static Atom UTF8_STRING = -1;
static Atom STRING = -1;

/*
int get_window_prop_wrapper(const xdo_t *xdo, Window window,
                            const char *property, int index, char **value) {
  int success = 0;
  unsigned char *buf = NULL;
  long nitems;
  Atom type;
  int size;

  success = xdo_get_window_property(xdo, window, property, &buf, &nitems, &type,
                                    &size);
  if (success != XDO_SUCCESS) {
    fprintf(stderr, "xdo_get_window_property failed!\n");
    return false;
  }

  if (size != 8) {
    fprintf(stderr, "size is %d\n", size);
  }
  if (index >= nitems) {
    fprintf(stderr, "Invalid index for %s: only %ld items\n", property, nitems);
    return false;
  }

  if (type == UTF8_STRING) {
    *value = (char *)buf;
    return true;
  }
  if (type == STRING) {
    char *item_ptr = (char *)buf;
    for (int i = 0; i < index; ++i) {
      item_ptr += strlen(item_ptr) + 1;
    }
    *value = strdup(item_ptr);
    free(buf);
    return true;
  }
  char *type_name = XGetAtomName(xdo->xdpy, type);
  fprintf(stderr, "Type for %s not implemented: %s\n", property, type_name);
  free(type_name);
  free(buf);
  return false;
}
*/

int watch_focus(Window windows[], int win_count) {
  xdo_t *xdo = xdo_new(NULL);
  for (int i = 0; i < win_count; ++i) {
    int ret = XSelectInput(xdo->xdpy, windows[i], FocusChangeMask);
    if (!ret) {
      fprintf(stderr, "XSelectInput error: %d\n", ret);
      return ret;
    }
  }

  Window window;
  int focused = -1;
  int mode, detail;
  // main loop
  while (1) {
    XEvent e;
    XNextEvent(xdo->xdpy, &e);

    switch (e.type) {
    case FocusIn:
      mode = ((XFocusInEvent *)&e)->mode;
      window = ((XFocusInEvent *)&e)->window;
      detail = ((XFocusInEvent *)&e)->detail;
      if (focused != window &&
          (mode == NotifyNormal || mode == NotifyWhileGrabbed)) {
        printf("focused %#lx\n", window);
        focused = 1;
      }
      break;
    case FocusOut:
      mode = ((XFocusOutEvent *)&e)->mode;
      window = ((XFocusOutEvent *)&e)->window;
      detail = ((XFocusOutEvent *)&e)->detail;
      if ((focused == window || focused == -1) &&
          (mode == NotifyNormal || mode == NotifyWhileGrabbed) &&
          detail != NotifyInferior) {
        printf("unfocused %lx\n", window);
        focused = 0;
      }
      break;
    }
  }

  xdo_free(xdo);
}

int main(int argc, char **argv) {
  int c;
  enum { opt_unused, opt_help };
  static struct option longopts[] = {
      {"help", no_argument, NULL, opt_help},
      {0, 0, 0, 0},
  };

  int option_index;
  while ((c = getopt_long(argc, argv, "h", longopts, &option_index)) != -1) {
    switch (c) {
    case 'h':
    case opt_help:
      printf(usage, argv[0]);
      return EXIT_SUCCESS;
      break;
    default:
      fprintf(stderr, usage, argv[0]);
      return EXIT_FAILURE;
    }
  }

  if (argc == optind) {
    fprintf(stderr, usage, argv[0]);
    return EXIT_FAILURE;
  }

  xdo_t *xdo = xdo_new(NULL);
  UTF8_STRING = XInternAtom(xdo->xdpy, "UTF8_STRING", 1);
  STRING = XInternAtom(xdo->xdpy, "STRING", 1);
  Window window = 0;
  // process windows to watch
  for (int i = optind; i < argc; ++i) {
    window = strtol(argv[i], NULL, 0);
    int ret = XSelectInput(xdo->xdpy, window, FocusChangeMask);
    if (!ret) {
      fprintf(stderr, "XSelectInput on window %#lx reported an error: %d\n",
              window, ret);
    }
  }

  const char *detail_lut[8];
  detail_lut[NotifyAncestor] = "NotifyAncestor";
  detail_lut[NotifyVirtual] = "NotifyVirtual";
  detail_lut[NotifyInferior] = "NotifyInferior";
  detail_lut[NotifyNonlinear] = "NotifyNonlinear";
  detail_lut[NotifyNonlinearVirtual] = "NotifyNonlinearVirtual";
  detail_lut[NotifyPointer] = "NotifyPointer";
  detail_lut[NotifyPointerRoot] = "NotifyPointerRoot";
  detail_lut[NotifyDetailNone] = "NotifyDetailNone";

  Window focused = 0;
  // main loop
  while (1) {
    XEvent e;
    XNextEvent(xdo->xdpy, &e);
    XFocusInEvent *fie;
    XFocusOutEvent *foe;
    XClassHint window_class;

    switch (e.type) {
    case FocusIn:
      fie = (XFocusInEvent *)&e;
      window = fie->window;
      if ((fie->mode == NotifyNormal || fie->mode == NotifyWhileGrabbed)) {
        XGetClassHint(xdo->xdpy, window, &window_class);
        printf("Got  focus on window %#07lx prev 0x%07lx (%s) \"%s\"\n", window,
               focused, detail_lut[fie->detail], window_class.res_class);
        focused = window;
      }
      break;
    case FocusOut:
      foe = (XFocusOutEvent *)&e;
      window = foe->window;
      if ((foe->mode == NotifyNormal || foe->mode == NotifyWhileGrabbed) &&
          foe->detail != NotifyInferior) {
        XGetClassHint(xdo->xdpy, window, &window_class);
        printf("Lost focus on window %#07lx prev 0x%07lx (%s) \"%s\"\n", window,
               focused, detail_lut[foe->detail], window_class.res_class);
        focused = 0;
      }
      break;
    }
  }

  xdo_free(xdo);
}
