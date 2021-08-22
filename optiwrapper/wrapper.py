#!/usr/bin/env python3
"""
Wrapper script to run games with Optimus, turn off xcape while focused, log
playtime, and more.
"""


import argparse
import atexit
import enum
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Set, Tuple, Union

import arrow
import notify2
from notify2 import dbus

from . import hooks, lib
from .lib import CONFIG_DIR, WRAPPER_DIR, logger, pgrep, watch_focus
from .libxdo import xdo_free, xdo_new, xdo_search_windows
from .settings import Config


class GpuType(enum.Enum):
    # pylint: disable=missing-docstring
    UNKNOWN = enum.auto()
    INTEL = enum.auto()
    # INTEL_NOUVEAU = enum.auto()
    NVIDIA = enum.auto()
    BUMBLEBEE = enum.auto()


# constants
WINDOW_WAIT_TIME = 60
PROCESS_WAIT_TIME = 20


# logging

logger.setLevel(logging.WARN)
logger.propagate = False
LOGFILE_FORMATTER = logging.Formatter(
    "{asctime:s} | {levelname:.1s}:{name:s}: {message:s}", style="{"
)
LOGFILES: Set[str] = set()


# log any uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception


DESC = """
A generic game wrapper script that can run the game on the discrete GPU, turn
off xcape while the game is focused, log playtime, and more.
"""
EPILOG = """
Game-specific configuration (command to run, whether to use primus, etc) should
be put in ~/Games/wrapper/settings/<GAME>.yaml. Run with "-h config" for more
information.

Examples:
  With a configuration file: %(prog)s -G Infinifactory
  For a Steam game: %(prog)s -G Game %%command%%
"""
CONFIG_HELP = """
Configuration file:
The following are keys in a mapping, read from ~/Games/wrapper/settings/<game>.yaml.

command:
    A sequence of strings, where the first is the command to run, followed by
    any arguments. If specified, the command and arguments passed on the
    command line will be ignored.

flags: A mapping to boolean values. All flags default to true.
  use_gpu:    Try to run on the discrete GPU
  fallback:   If the discrete GPU is unavailable, then run without it
  use_primus: Use the primus backend for optirun
  vsync:      Enable vsync (reduces tearing, but more input lag)
  is_64_bit:  Used to remove the extra Steam gameoverlay.so LD_PRELOAD entry

process_name:
    The process name, for tracking when the game has exited. Only needed if the
    initial process isn't the same as the actual game (e.g. a launcher)

window_title:
    Name of main game window (regular expression).
    Can be found in the Alt-Tab menu or "xprop _NET_WM_NAME".

window_class:
    Class of main game window (regular expression, must match entire string).
    Can be found by looking at the first string returned by "xprop WM_CLASS".

hooks: A sequence of modules to load from ~/Games/wrapper/hooks/. Common hooks:
  - stop_xcape: Disables xcape (maps ctrl to escape) while the game is focused.
  - hide_top_bar: Hides the top menu bar (in GNOME) when the game is focused.
  - invert_scroll: Inverts the direction of the scroll wheel while in-game.
"""


TIME_LOGFILE = None


class Event(enum.Enum):
    # pylint: disable=missing-docstring
    START = enum.auto()
    STOP = enum.auto()
    UNFOCUS = enum.auto()
    FOCUS = enum.auto()
    DIE = enum.auto()


def get_gpu_type(needs_gpu: bool) -> GpuType:
    # construct_command_line
    if (
        os.environ.get("NVIDIA_XRUN") is not None
        or os.readlink("/etc/X11/xorg.conf.d/20-dgpu.conf")
        == "/etc/X11/video/20-nvidia.conf"
    ):
        return GpuType.NVIDIA

    # from main
    if needs_gpu:
        try:
            optirun_works = (
                subprocess.run(["optirun", "--silent", "true"], check=True).returncode
                == 0
            )
        except FileNotFoundError:
            optirun_works = False

        if optirun_works:
            return GpuType.BUMBLEBEE
        return GpuType.INTEL
    return GpuType.UNKNOWN


def dump_test_config(config: Config) -> str:
    """
    Dumps a set of config files for comparing against the bash script.
    """
    out = []
    out.append("COMMAND: " + " ".join(map(str, config.command)))

    out.append("OUTPUT_FILES:")
    for outfile in sorted(LOGFILES):
        out.append(f' "{outfile}"')

    def dump_flag(name: str) -> None:
        option = name.upper()
        flag_val = "y" if getattr(config.flags, name) else "n"
        out.append(f'{option}: "{flag_val}"')

    def dump(name: str) -> None:
        option = name.upper()
        val: Union[str, List[str]] = getattr(config, name)
        if not val:
            out.append(f"{option}:")
        elif isinstance(val, (str, Path)):
            out.append(f'{option}: "{val}"')
        elif isinstance(val, list):
            out.append("{}: {}".format(option, " ".join(map('"{:s}"'.format, val))))

    dump("game")
    dump_flag("use_gpu")
    dump_flag("fallback")
    dump_flag("use_primus")
    dump_flag("vsync")
    dump("process_name")
    dump("window_title")
    dump("window_class")
    dump("hooks")

    return "\n".join(out)


def setup_logfile(logfile: Any) -> None:
    """
    Adds a log file to the logger.
    """
    logpath = Path(logfile).resolve(strict=False)
    if str(logpath) not in LOGFILES:
        handler = logging.FileHandler(logpath, mode="w")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(LOGFILE_FORMATTER)
        logger.addHandler(handler)
        LOGFILES.add(str(logpath))


def get_config(
    args: argparse.Namespace,  # pylint: disable=redefined-outer-name
) -> Config:
    """
    Constructs a configuration from the given arguments.
    """
    # order of configuration precedence, from highest to lowest:
    #  1. command line parameters (<command>, --hide-top-bar, --no-discrete)
    #  2. game configuration file (--game)

    # parse game config file
    assert args.game is not None
    try:
        config = Config.load(args.game)
    except OSError:
        logger.error(
            'The configuration file for "%s" was not found in %s.',
            args.game,
            CONFIG_DIR,
        )
        sys.exit(1)

    setup_logfile(WRAPPER_DIR / "logs" / f"{config.game}.log")

    # check arguments
    if args.command:
        # print('cli command:', args.command)
        if not config.command:
            config.command = args.command
        else:
            if config.command[0] != args.command[0]:
                logger.warning(
                    "Different command given in config file and command line"
                )
            config.command = args.command

    if args.use_gpu is not None:
        config.flags.use_gpu = args.use_gpu

    if args.hide_top_bar is not None:
        if config.hooks:
            if "hide_top_bar" not in config.hooks:
                config.hooks.append("hide_top_bar")
        else:
            config.hooks = ["hide_top_bar"]

    return config


def construct_command_line(
    config: Config, gpu_type: GpuType
) -> Tuple[List[str], Dict[str, str]]:
    """
    Constructs a full command line and environment dict from a configuration
    """
    cmd_args: List[str] = []
    environ: Dict[str, str] = dict()
    # check if we're running under nvidia-xrun
    if gpu_type is GpuType.NVIDIA:
        if not config.flags.vsync:
            environ["__GL_SYNC_TO_VBLANK"] = "0"
    elif not config.flags.vsync:
        environ["vblank_mode"] = "0"
    elif config.flags.use_gpu:
        cmd_args.append("optirun")
        if logger.isEnabledFor(logging.DEBUG):
            cmd_args.append("--debug")
        if config.flags.use_primus:
            cmd_args.extend("-b primus".split())
    if config.command:
        cmd_args.extend(config.command)
    return cmd_args, environ


def notify(msg: str, level: int = logging.INFO, log: bool = False) -> None:
    icon = {
        logging.INFO: "dialog-information",
        logging.WARNING: "dialog-warning",
        logging.ERROR: "dialog-error",
    }.get(level, "dialog-information")
    if log:
        logger.log(level, msg)
    if notify2 is not None:
        n = notify2.Notification("optiwrapper", msg, icon)
        n.show()


class FocusThread(threading.Thread):
    def __init__(self, main: "Main"):
        super().__init__()
        self.main = main
        self.daemon = True
        self.kwargs: Dict[str, Union[bool, int, str]] = {
            "only_visible": True,
            "require_all": True,  # require all conditions to match
        }

        # check if we're in a WM
        self.in_window_manager = (
            subprocess.run(
                ["wmctrl", "-m"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )

        self.track_focus = False
        if main.cfg.window_title:
            self.kwargs["winname"] = main.cfg.window_title
            self.track_focus = True
        if main.cfg.window_class:
            self.kwargs["winclassname"] = "^" + main.cfg.window_class + "$"
            self.track_focus = True

        if not self.in_window_manager:
            logger.debug("not in WM")

    def run(self) -> None:
        if not self.track_focus:
            return
        if not self.in_window_manager:
            self.main.focused()
            return
        logger.debug("in WM, tracking focus")

        # if a window is closed, search for new matching windows again
        closed_win = 1
        logger.debug("waiting for window...")
        while closed_win > 0 and lib.running:
            xdo = xdo_new(None)
            wins = xdo_search_windows(xdo, **self.kwargs)  # type: ignore
            window_start_time = time.time()
            while not wins and lib.running:
                if time.time() > window_start_time + WINDOW_WAIT_TIME:
                    notify(
                        f"Window not found within {WINDOW_WAIT_TIME} seconds",
                        logging.ERROR,
                        log=True,
                    )
                    sys.exit(1)
                time.sleep(0.1)
                wins = xdo_search_windows(xdo, **self.kwargs)  # type: ignore
            xdo_free(xdo)
            xdo = None
            if not lib.running:
                logger.debug("game stopped; focus thread exiting")
                return
            if len(wins) > 1:
                logger.error(
                    "found multiple windows (%s): can't track focus correctly",
                    ", ".join(map("0x{:x}".format, wins)),
                )
                return
            logger.debug("found window: 0x%x", wins[0])
            closed_win = next(
                watch_focus(
                    wins,
                    lambda evt: self.main.focused(),
                    lambda evt: self.main.unfocused(),
                )
            )
            logger.debug("watch_focus returned %x", closed_win)
            time.sleep(0.1)
        if closed_win <= 0:
            logger.debug("window closed")


# initialize notification system
try:
    notify2.init("optiwrapper")
except dbus.exceptions.DBusException:
    notify2 = None


def parse_args() -> argparse.Namespace:
    # command line arguments
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        description=DESC,
        epilog=EPILOG,
    )
    parser.add_argument(
        "-h", "--help", help="show this help message and exit", nargs="?", const="help"
    )
    parser.add_argument(
        "command",
        metavar="COMMAND",
        help="specify command to be run",
        nargs=argparse.REMAINDER,
    )
    parser.add_argument(
        "-G",
        "--game",
        metavar="GAME",
        help="specify a game (will search for a config file)",
    )
    parser.add_argument(
        "-f",
        "--hide-top-bar",
        help="hide the top bar (needed for fullscreen in some games)",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "-d", "--debug", help="enable debugging output", action="store_true"
    )
    parser.add_argument(
        "-n",
        "--no-discrete",
        help="don't use discrete graphics",
        dest="use_gpu",
        action="store_false",
        default=None,
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="log all output to a file (will overwrite, not append)",
        dest="outfile",
    )
    parser.add_argument("-c", "--classname", help="window classname to match against")
    parser.add_argument("-t", "--test", action="store_true")

    args = parser.parse_args()

    if args.help == "config":
        print(CONFIG_HELP)
        sys.exit(0)
    elif args.help is not None:
        parser.print_help()
        sys.exit(0)

    if args.game is None:
        parser.error("the following arguments are required: -G/--game")

    return args


class Main:
    def __init__(self) -> None:
        # create console log handler and set level to debug, as the actual level
        # selection is done in the logger
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(
            logging.Formatter("{levelname:.1s}:{name}: {message}", style="{")
        )
        logger.addHandler(ch)

        args = parse_args()
        # print(args)

        # setup logging
        if args.debug:
            logger.setLevel(logging.DEBUG)

        if args.outfile is not None:
            setup_logfile(args.outfile)

        self.cfg = get_config(args)

        cfg_err_msg = self.cfg.check()
        if cfg_err_msg is not None:
            logger.error(cfg_err_msg)
            sys.exit(1)

        gpu_type = get_gpu_type(needs_gpu=self.cfg.flags.use_gpu)
        logger.debug("GPU: %s", gpu_type)

        # check if discrete GPU works, notify if not
        if self.cfg.flags.use_gpu and gpu_type not in (
            GpuType.NVIDIA,
            GpuType.BUMBLEBEE,
        ):
            if self.cfg.flags.fallback:
                notify(
                    "Discrete GPU not working, falling back to integrated GPU",
                    logging.ERROR,
                    True,
                )
                self.cfg.flags.use_gpu = False
            else:
                notify("Discrete GPU not working, quitting", logging.ERROR, True)
                sys.exit(1)

        # if args.test:
        #     print(dump_test_config(cfg))
        #     sys.exit(0)

        logger.debug("\n%s", self.cfg.pretty())

        # setup time logging
        self.time_logfile = WRAPPER_DIR / f"time/{self.cfg.game}.log"
        # create directory if it doesn't exist
        self.time_logfile.parent.mkdir(parents=True, exist_ok=True)

        # load hooks
        hooks.register_hooks()
        for hook_name in self.cfg.hooks:
            hooks.load_hook(hook_name)

        # setup command
        self.command, self.env_override = construct_command_line(self.cfg, gpu_type)
        logger.debug("Command: %s", repr(self.command))

        # remove overlay library for wrong architecture
        self.env_override.update(lib.remove_overlay(self.cfg.flags.is_64_bit))
        if "LD_PRELOAD" in self.env_override:
            logger.debug('Fixed LD_PRELOAD: now "%s"', self.env_override["LD_PRELOAD"])

    def log_time(self, event: Event) -> None:
        """
        Writes a message to the time logfile, if one exists.
        """
        message = {
            Event.START: "game started",
            Event.STOP: "game stopped",
            Event.UNFOCUS: "user left",
            Event.FOCUS: "user returned",
            Event.DIE: "wrapper died",
        }[event]

        timestamp = arrow.now().format("YYYY-MM-DDTHH:mm:ss.SSSZZ")
        with open(self.time_logfile, "a") as logfile:
            logfile.write(f"{timestamp}: {message}\n")

    def started(self) -> None:
        """
        To be run when the game starts.
        """
        logger.debug("game starting...")
        self.log_time(Event.START)
        for hook in hooks.get_hooks().values():
            hook.on_start()

    def stopped(self, killed: bool = False) -> None:
        """
        To be run after the game exits.
        """
        lib.running = False
        logger.debug("game stopped")
        if killed:
            self.log_time(Event.DIE)
        else:
            self.log_time(Event.STOP)
        for hook in hooks.get_hooks().values():
            hook.on_stop()

    def focused(self) -> None:
        """
        To be run when the game window is focused.
        """
        logger.debug("window focused")
        if lib.running:
            self.log_time(Event.FOCUS)
        for hook in hooks.get_hooks().values():
            hook.on_focus()

    def unfocused(self) -> None:
        """
        To be run when the game window loses focus.
        """
        logger.debug("window unfocused")
        if lib.running:
            self.log_time(Event.UNFOCUS)
        for hook in hooks.get_hooks().values():
            hook.on_unfocus()

    def run(self) -> NoReturn:
        def cb_signal_handler(signum, frame):
            """
            Write a message to both logs, then die.
            """
            self.stopped(killed=True)
            atexit.unregister(self.stopped)
            logger.error("Killed by external signal %d", signum)
            sys.exit(1)

        # clean up when killed by a signal
        signal.signal(signal.SIGTERM, cb_signal_handler)
        signal.signal(signal.SIGINT, cb_signal_handler)
        atexit.register(self.stopped)
        self.started()

        # run command
        logger.debug(
            "env vars: %s",
            " ".join(k + "=" + v for k, v in self.env_override.items()),
        )
        logger.debug("CWD: %s", Path().absolute())
        proc = subprocess.Popen(self.command, env={**os.environ, **self.env_override})
        # track focus
        ft = FocusThread(self)
        ft.start()

        if not self.cfg.process_name:
            # just wait for subprocess to finish
            logger.debug("waiting on subprocess %d", proc.pid)
            proc.wait()
            logger.debug("subprocess %d done, exiting wrapper", proc.pid)
        else:
            # find process
            time.sleep(2)
            pattern = self.cfg.process_name
            proc_start_time = time.time()
            procs = pgrep(pattern)
            logger.debug("found: %s", procs)
            while len(procs) != 1:
                if time.time() > proc_start_time + PROCESS_WAIT_TIME:
                    logger.error(
                        "Process not found within %d seconds", PROCESS_WAIT_TIME
                    )
                    notify("Failed to find game PID, quitting", logging.ERROR)
                    sys.exit(1)
                procs = pgrep(pattern)
                logger.debug("found: %s", procs)
                if len(procs) > 1:
                    logger.error("Multiple matching processes:")
                    for p in procs:
                        logger.error("%s", p)
                    sys.exit(1)
                time.sleep(0.5)

            # found single process to wait for
            procs[0].wait_for_process(use_spinner=False)
        sys.exit(0)


def run() -> NoReturn:
    Main().run()
