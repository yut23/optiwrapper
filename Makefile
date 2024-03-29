CC=clang
CFLAGS?=-Wall -Wextra
CFLAGS+=-g# -fsanitize=address -fno-omit-frame-pointer
LDFLAGS=-lX11
CXX=clang++
CXXFLAGS=$(CFLAGS) -std=c++20

.PHONY: all clean ui lint
all: watch_focus myxdo.so myxdo_test ui
ui: optiwrapper/configurator/ui/settingswindow.py

watch_focus: src/watch_focus.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^

myxdo.so: src/myxdo.c
	$(CC) $(CFLAGS) -fPIC -shared -lX11 -o $@ $^

myxdo_test: src/myxdo_test.cpp myxdo.so
	$(CXX) $(CXXFLAGS) -L. -l:myxdo.so -Wl,-rpath '-Wl,$$ORIGIN' -o $@ $^

# create ui directory if it doesn't exist
optiwrapper/configurator/ui:
	mkdir -p $@

optiwrapper/configurator/ui/settingswindow.py: optiwrapper/configurator/SettingsWindow.ui | optiwrapper/configurator/ui
	uic -g python -o $@ $<

clean:
	rm -f watch_focus myxdo.so myxdo_test optiwrapper/configurator/ui/*.py

lint:
	isort --check optiwrapper
	flake8 optiwrapper
	mypy optiwrapper
	pylint --disable=fixme optiwrapper
