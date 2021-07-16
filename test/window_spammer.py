import sys
import time

from Xlib import X, display

if __name__ == "__main__":
    if len(sys.argv) > 1:
        delay = float(sys.argv[1])
    else:
        delay = 0.016

    d = display.Display()
    print(f"Creating and destroying a window every {delay}s")
    root = d.screen().root
    while True:
        w = root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        d.flush()
        time.sleep(delay / 2)
        w.destroy()
        d.flush()
        time.sleep(delay / 2)
