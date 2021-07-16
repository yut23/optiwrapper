CC=clang
CFLAGS?=-Wall
CFLAGS+=-g# -fsanitize=address -fno-omit-frame-pointer
LDFLAGS=-lX11
CXX=clang++
CXXFLAGS=$(CFLAGS)

all: watch_focus myxdo myxdo_test

watch_focus: src/watch_focus.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^

.PHONY: myxdo
myxdo: myxdo.so

myxdo.so: src/myxdo.c
	$(CC) $(CFLAGS) -fPIC -shared -lX11 -o $@ $^

myxdo_test: src/myxdo_test.cpp myxdo.so
	$(CXX) $(CXXFLAGS) -L. -l:myxdo.so -Wl,-rpath '-Wl,$$ORIGIN' -o $@ $^

clean:
	rm -f watch_focus myxdo.so myxdo_test
