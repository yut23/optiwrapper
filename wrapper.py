#!/usr/bin/env python3
"""
Wrapper script to run games with Optimus, turn off xcape while focused, log
playtime, and more.
"""


import argparse
import atexit
import configparser
import enum
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    TypedDict,
    Union,
    cast,
)

import arrow
import notify2
from notify2 import dbus

import hooks
import lib
from lib import pgrep, watch_focus
from libxdo import xdo_free, xdo_new, xdo_search_windows


class ConfigDict(TypedDict, total=False):
    cmd: List[str]
    game: str
    use_gpu: bool
    fallback: bool
    use_primus: bool
    force_vsync: bool
    is_32_bit: bool
    proc_name: str
    window_title: str
    window_class: str
    hooks: List[str]


ConfigKeys = Literal[
    "cmd",
    "game",
    "use_gpu",
    "fallback",
    "use_primus",
    "force_vsync",
    "is_32_bit",
    "proc_name",
    "window_title",
    "window_class",
    "hooks",
]


class GpuType(enum.Enum):
    # pylint: disable=missing-docstring
    UNKNOWN = enum.auto()
    INTEL = enum.auto()
    # INTEL_NOUVEAU = enum.auto()
    NVIDIA = enum.auto()
    BUMBLEBEE = enum.auto()


GPU_TYPE = GpuType.UNKNOWN


CONFIG_DEFAULTS = ConfigDict(
    use_gpu=True, fallback=True, use_primus=True, force_vsync=True, is_32_bit=False
)


CONFIG_TYPES = cast(
    Dict[ConfigKeys, type], ConfigDict.__annotations__  # pylint: disable=no-member
)

# constants
WINDOW_WAIT_TIME = 40
PROCESS_WAIT_TIME = 20


# logging

logger = logging.getLogger("optiwrapper")  # pylint: disable=invalid-name
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


TIME_LOGFILE = None


# constants
GAMES_DIR = Path.home() / "Games"
WRAPPER_DIR = GAMES_DIR / "wrapper"

DESC = """
A generic game wrapper script that can run the game on the discrete GPU, turn
off xcape while the game is focused, log playtime, and more.
"""
EPILOG = """
Game-specific configuration (command to run, whether to use primus, etc) should
be put in ~/Games/wrapper/config/<GAME>.cfg. Run with "-h config" for more
information.

Examples:
  With a configuration file: %(prog)s -G Infinifactory
  For a Steam game: %(prog)s %%command%%
"""
CONFIG_HELP = """
Configuration file:
The following are loaded as variables from ~/Games/wrapper/config/<game>.cfg.
Boolean values are either "y" or "n".

CMD: The command to run, as an array of arguments. If specified, any arguments
  passed on the command line will be ignored.

GAME: The game's name (only needed if the config file is specified using a path)

USE_GPU [y]: Whether to run on the discrete GPU

FALLBACK [y]: Whether to run the game even if the discrete GPU is unavailable

USE_PRIMUS [y]: Whether to run with primus (optirun -b primus)

FORCE_VSYNC [y]: Whether to run primus with vblank_mode=0

IS_32_BIT [n]: Whether the executable is 32-bit (for removing extra Steam
  gameoverlay.so entry)

PROC_NAME: The process name, for tracking when the game has exited. Only needed
  if the initial process isn't the same as the actual game (e.g. a launcher)

WINDOW_TITLE: Name of main game window (can use regular expressions). Can be
  found through Alt-Tab menu or "xprop _NET_WM_NAME".

WINDOW_CLASS: Class of main game window (must match exactly). Can be found by
  looking at the first string returned by "xprop WM_CLASS".

HOOKS: Names of files to load from ~/Games/wrapper/hooks/. Common hooks:
  hide_top_bar: Hides the top menu bar when the game is focused.
  stop_xcape: Disables xcape (maps ctrl to escape) while the game is focused.
  mouse_accel: Disables mouse acceleration while the game is focused.
"""


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


def format_config(config: ConfigDict) -> str:
    """
    Pretty-formats a set of config options.
    """
    out = []
    option_width = max(len(o) for o in config.keys()) + 1
    for option, value in config.items():
        out.append("{:<{width}s} {}".format(option + ":", value, width=option_width))
    return "\n".join(out)


def dump_test_config(config: ConfigDict) -> str:
    """
    Dumps a set of config files for comparing against the bash script.
    """
    out = []
    out.append("COMMAND: " + " ".join(map("{:s}".format, config["cmd"])))

    out.append("OUTPUT_FILES:")
    for outfile in sorted(LOGFILES):
        out.append(' "{:s}"'.format(outfile))

    def dump(name: ConfigKeys) -> None:
        option = name.upper()
        type_ = CONFIG_TYPES[name]
        val = config.get(name, None)
        if val is None:
            out.append("{:s}:".format(option))
        elif type_ is str or type_ is Path:
            out.append('{:s}: "{:s}"'.format(option, val))
        elif type_ is bool:
            out.append('{:s}: "{:s}"'.format(option, "y" if val else "n"))
        elif type_ is List[str]:
            out.append(
                "{:s}: {:s}".format(
                    option, " ".join(map('"{:s}"'.format, cast(List[str], val)))
                )
            )

    dump("game")
    dump("use_gpu")
    dump("fallback")
    dump("use_primus")
    dump("force_vsync")
    dump("proc_name")
    dump("window_title")
    dump("window_class")
    dump("hooks")

    return "\n".join(out)


class ConfigException(Exception):
    """
    An error caused by an invalid configuration file.
    """


def parse_config_file(data: str) -> ConfigDict:
    """
    Parses the contents of a configuration file.
    """

    def parse_option(option: str, value: Any) -> Tuple[ConfigKeys, Any]:
        if option.lower() not in CONFIG_TYPES:
            raise ConfigException("Invalid option: {}".format(option))
        dest = cast(ConfigKeys, option.lower())
        type_ = CONFIG_TYPES[dest]

        if type_ is str:
            vals = shlex.split(value)
            if len(vals) == 1:
                # strip quotes if there's only one string
                return dest, vals[0]
            return dest, value
        if type_ is List[str]:
            if not (value and value[0] == "(" and value[-1] == ")"):
                raise ConfigException(
                    "{} must be an array, surrounded by parens".format(option)
                )
            return dest, shlex.split(value[1:-1])
        if type_ is bool:
            if value not in ("y", "n"):
                raise ConfigException('{} must be "y" or "n"'.format(option))
            return dest, value == "y"
        if type_ is Path:
            return dest, Path(value).expanduser().absolute()
        raise ConfigException("Internal error: argument type not found for " + option)

    config_p = configparser.ConfigParser()
    config_p.optionxform = str  # type: ignore
    config_p.read_string("[section]\n" + data)
    config = ConfigDict()
    for opt, val in config_p.items("section"):
        dest, value = parse_option(opt, val)
        config[dest] = value

    return config


def check_config(config: ConfigDict) -> Optional[str]:
    """
    Checks if a configuration is valid.

    Returns None if it is valid, or an error message if not.
    """
    # a command is required
    if not config["cmd"]:
        return "No command specified"

    # the command must be a valid executable
    if not os.path.isfile(config["cmd"][0]):
        return 'The file "{:s}" specified for command does not exist.'.format(
            config["cmd"][0]
        )
    if not os.access(config["cmd"][0], os.X_OK):
        return 'The file "{:s}" specified for command is not executable.'.format(
            config["cmd"][0]
        )

    return None


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
) -> ConfigDict:
    """
    Constructs a configuration from the given arguments.
    """
    config = CONFIG_DEFAULTS.copy()

    # order of configuration precedence, from highest to lowest:
    #  1. command line parameters (<command>, --hide-top-bar, --no-discrete)
    #  2. game configuration file (--game)

    # parse game config file
    config["game"] = args.game
    assert config["game"] is not None
    try:
        with open(WRAPPER_DIR / "config" / (config["game"] + ".cfg")) as file:
            config_data = file.read()
        config.update(parse_config_file(config_data))
    except OSError:
        logger.error(
            'The configuration file for "%s" was not found in %s.',
            config["game"],
            WRAPPER_DIR / "config",
        )
        sys.exit(1)

    setup_logfile(WRAPPER_DIR / "logs" / (config["game"] + ".log"))

    # check arguments
    if args.command:
        # print('cli command:', args.command)
        if "cmd" not in config or not config["cmd"]:
            config["cmd"] = args.command
        elif "cmd" in config and config["cmd"]:
            if config["cmd"][0] != args.command[0]:
                logger.warning(
                    "Different command given in config file and command line"
                )
            config["cmd"] = args.command

    if args.use_gpu is not None:
        config["use_gpu"] = args.use_gpu

    if args.hide_top_bar is not None:
        if "hooks" in config:
            if "hide_top_bar" not in config["hooks"]:
                config["hooks"].append("hide_top_bar")
        else:
            config["hooks"] = ["hide_top_bar"]

    return config


def construct_command_line(config: ConfigDict) -> Tuple[List[str], Dict[str, str]]:
    """
    Constructs a full command line and environment dict from a configuration
    """
    cmd_args: List[str] = []
    environ: Dict[str, str] = dict()
    # check if we're running under nvidia-xrun
    if GPU_TYPE is GpuType.NVIDIA:
        if not config["force_vsync"]:
            environ["__GL_SYNC_TO_VBLANK"] = "0"
    elif not config["force_vsync"]:
        environ["vblank_mode"] = "0"
    elif config["use_gpu"]:
        cmd_args.append("optirun")
        if logger.level == logging.DEBUG:
            cmd_args.append("--debug")
        if config["use_primus"]:
            cmd_args.extend("-b primus".split())
    if "cmd" in config:
        cmd_args.extend(config["cmd"])
    return cmd_args, environ


def log_time(event: Event) -> None:
    """
    Writes a message to the time logfile, if one exists.
    """
    if TIME_LOGFILE is not None:
        message = {
            Event.START: "game started",
            Event.STOP: "game stopped",
            Event.UNFOCUS: "user left",
            Event.FOCUS: "user returned",
            Event.DIE: "wrapper died",
        }[event]

        timestamp = arrow.now().format("YYYY-MM-DDTHH:mm:ss.SSSZZ")
        with open(TIME_LOGFILE, "a") as logfile:
            logfile.write(f"{timestamp}: {message}\n")


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


def start() -> None:
    """
    To be run when the game starts.
    """
    logger.debug("game starting...")
    log_time(Event.START)
    for hook in hooks.get_hooks().values():
        hook.on_start()


def stop(killed: bool = False) -> None:
    """
    To be run after the game exits.
    """
    lib.running = False
    logger.debug("game stopped")
    if killed:
        log_time(Event.DIE)
    else:
        log_time(Event.STOP)
    for hook in hooks.get_hooks().values():
        hook.on_stop()


def focus() -> None:
    """
    To be run when the game window is focused.
    """
    logger.debug("window focused")
    if lib.running:
        log_time(Event.FOCUS)
    for hook in hooks.get_hooks().values():
        hook.on_focus()


def unfocus() -> None:
    """
    To be run when the game window loses focus.
    """
    logger.debug("window unfocused")
    if lib.running:
        log_time(Event.UNFOCUS)
    for hook in hooks.get_hooks().values():
        hook.on_unfocus()


class FocusThread(threading.Thread):
    def __init__(self, config: ConfigDict):
        super().__init__()
        self.daemon = True
        self.kwargs: Dict[str, Union[bool, int, str]] = {
            "only_visible": True,
            "require_all": True,  # require all conditions to match
        }
        if "window_title" in config:
            self.kwargs["winname"] = config["window_title"]
        if "window_class" in config:
            self.kwargs["winclassname"] = "^" + config["window_class"] + "$"

    def run(self) -> None:
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
                watch_focus(wins, lambda evt: focus(), lambda evt: unfocus(),)
            )
            logger.debug("watch_focus returned %x", closed_win)
            time.sleep(0.1)
        if closed_win <= 0:
            logger.debug("window closed")


if __name__ == "__main__":
    # pylint: disable=invalid-name

    # create console log handler and set level to debug, as the actual level
    # selection is done in the logger
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("{levelname:.1s}:{name}: {message}", style="{"))
    logger.addHandler(ch)

    # initialize notification system
    try:
        notify2.init("optiwrapper")
    except dbus.exceptions.DBusException:
        notify2 = None

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
        required=True,
        help=("specify a game (will search for a config file)"),
    )
    parser.add_argument(
        "-f",
        "--hide-top-bar",
        help=("hide the top bar (needed for fullscreen in some games)"),
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
        help=("log all output to a file (will overwrite, not append)"),
        dest="outfile",
    )
    parser.add_argument("-c", "--classname", help="window classname to match against")
    parser.add_argument("-t", "--test", action="store_true")
    args = parser.parse_args()
    # print(args)

    if args.help == "config":
        print(CONFIG_HELP)
        sys.exit(0)
    elif args.help is not None:
        parser.print_help()
        sys.exit(0)

    # setup logging
    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.outfile is not None:
        setup_logfile(args.outfile)

    cfg = get_config(args)

    cfg_err_msg = check_config(cfg)
    if cfg_err_msg is not None:
        logger.error(cfg_err_msg)
        sys.exit(1)

    GPU_TYPE = get_gpu_type(needs_gpu=cfg["use_gpu"])
    logger.debug("GPU: %s", GPU_TYPE)

    # check if discrete GPU works, notify if not
    if cfg["use_gpu"] and GPU_TYPE not in (GpuType.NVIDIA, GpuType.BUMBLEBEE):
        if cfg["fallback"]:
            notify(
                "Discrete GPU not working, falling back to integrated GPU",
                logging.ERROR,
                True,
            )
            cfg["use_gpu"] = False
        else:
            notify("Discrete GPU not working, quitting", logging.ERROR, True)
            sys.exit(1)

    if args.test:
        print(dump_test_config(cfg))
        sys.exit(0)

    logger.debug("\n%s", format_config(cfg))

    # setup time logging
    if "game" in cfg:
        TIME_LOGFILE = WRAPPER_DIR / "time/{}.log".format(cfg["game"])
        # create directory if it doesn't exist
        TIME_LOGFILE.parent.mkdir(parents=True, exist_ok=True)

    # setup command
    command, env_override = construct_command_line(cfg)
    logger.debug("Command: %s", repr(command))

    # load hooks
    hooks.register_hooks()
    for hook_name in cfg.get("hooks", []):
        hooks.load_hook(hook_name)

    # remove overlay library for wrong architecture
    env_override.update(lib.remove_overlay(cfg["is_32_bit"]))
    if "LD_PRELOAD" in env_override:
        logger.debug('Fixed LD_PRELOAD: now "%s"', env_override["LD_PRELOAD"])

    def cb_signal_handler(signum, frame):
        """
        Write a message to both logs, then die.
        """
        stop(killed=True)
        atexit.unregister(stop)
        logger.error("Killed by external signal %d", signum)
        sys.exit(1)

    # clean up when killed by a signal
    signal.signal(signal.SIGTERM, cb_signal_handler)
    signal.signal(signal.SIGINT, cb_signal_handler)
    atexit.register(stop)
    start()

    # check if we're in a WM
    in_window_manager = (
        subprocess.run(
            ["wmctrl", "-m"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )

    # run command
    logger.debug(
        "env vars: %s", " ".join(k + "=" + v for k, v in env_override.items()),
    )
    logger.debug("CWD: %s", Path().absolute())
    proc = subprocess.Popen(command, env={**os.environ, **env_override})
    if ("window_class" in cfg or "window_title" in cfg) and in_window_manager:
        logger.debug("in WM, tracking focus")
        ft = FocusThread(cfg)
        ft.start()

    if not in_window_manager:
        # add focus event for better time tracking
        logger.debug("not in WM")
        focus()

    if "proc_name" not in cfg:
        # just wait for subprocess to finish
        logger.debug("waiting on subprocess %d", proc.pid)
        proc.wait()
        logger.debug("subprocess %d done, exiting wrapper", proc.pid)
    else:
        # find process
        time.sleep(2)
        pattern = cfg["proc_name"]
        proc_start_time = time.time()
        procs = pgrep(pattern)
        logger.debug("found: %s", procs)
        while len(procs) != 1:
            if time.time() > proc_start_time + PROCESS_WAIT_TIME:
                logger.error("Process not found within %d seconds", PROCESS_WAIT_TIME)
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
