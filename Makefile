CC=clang
CFLAGS?=-Wall
CFLAGS+=-g
LDFLAGS=-lxdo -lX11

all: watch_focus myxdo

watch_focus: src/watch_focus.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^

.PHONY: myxdo
myxdo: myxdo.so

myxdo.so: src/myxdo.c
	$(CC) -fPIC -shared -Wl,-soname,$(@:%.so=%) -lX11 -o $@ $^

clean:
	rm -f watch_focus myxdo.so
