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
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union, cast

import arrow
import notify2
from proc.core import Process

import gnome_shell_ext as gse
import lib
from lib import myxdo, pgrep, search_windows, watch_focus

ConfigDict = Dict[str, Union[None, str, List[str], bool, Path]]


# constants
WINDOW_WAIT_TIME = 20
PROCESS_WAIT_TIME = 20


# logging

logger = logging.getLogger("optiwrapper")  # pylint: disable=invalid-name
logger.setLevel(logging.WARN)
logger.propagate = False
LOGFILE_FORMATTER = logging.Formatter(
    "{asctime:s} | {levelname:.1s}:{name:s}: {message:s}", style="{"
)
LOGFILES: Set[str] = set()

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

CMD: The executable to run. If relative, the path will be resolved from the
  current working directory.

ARGS: Any extra arguments to pass to the executable, as an array.

GAME: The game's name (only needed if the config file is specified using a path)

LOGFILE: Path to a log file. If set but empty, no log file will be created.
  If unset, will default to "~/Games/wrapper/logs/<GAME>.log".

USE_GPU [y]: Whether to run on the discrete GPU

FALLBACK [y]: Whether to run the game even if the discrete GPU is unavailable

PRIMUS [y]: Whether to run with primus (optirun -b primus)

VSYNC [y]: Whether to run primus with vblank_mode=0

HIDE_TOP_BAR [n]: Whether to hide the top bar when the game is run.

PROC_NAME: The process name, for tracking when the game has exited. Only needed
  if the initial process isn't the same as the actual game (e.g. a launcher)

STOP_XCAPE [n]: Whether to disable xcape while the game is focused.
  Requires WINDOW_TITLE or WINDOW_CLASS to be specified.

WINDOW_TITLE: Name of main game window (can use regular expressions)

WINDOW_CLASS: Class of main game window (must match exactly). Can be found by
  looking at the first string returned by "xprop WM_CLASS".
"""


CONFIG_OPTIONS = {
    "CMD": ("cmd", Path, None),
    "ARGS": ("args", list, None),
    "GAME": ("game", str, None),
    "LOGFILE": ("logfile", Path, None),
    "USE_GPU": ("use_gpu", bool, True),
    "FALLBACK": ("fallback", bool, True),
    "PRIMUS": ("use_primus", bool, True),
    "VSYNC": ("force_vsync", bool, True),
    "HIDE_TOP_BAR": ("hide_top_bar", bool, False),
    "IS_32_BIT": ("is_32_bit", bool, False),
    "STOP_XCAPE": ("stop_xcape", bool, False),
    "PROC_NAME": ("proc_name", str, None),
    "WINDOW_TITLE": ("window_title", str, None),
    "WINDOW_CLASS": ("window_class", str, None),
}

CONFIG_DEFAULTS: Dict[str, Any] = {
    dest: default for dest, type_, default in CONFIG_OPTIONS.values()
}


class Event(enum.Enum):
    # pylint: disable=missing-docstring
    START = enum.auto()
    STOP = enum.auto()
    UNFOCUS = enum.auto()
    FOCUS = enum.auto()
    DIE = enum.auto()


def format_config(options: Mapping[str, Any]) -> str:
    """
    Pretty-formats a set of config options.
    """
    out = []
    option_width = max(len(o) for o in options.keys()) + 1
    for option, value in options.items():
        out.append("{:<{width}s} {}".format(option + ":", value, width=option_width))
    return "\n".join(out)


def dump_test_config(options: Mapping[str, Any]) -> str:
    """
    Dumps a set of config files for comparing against the bash script.
    """
    out = []
    temp = 'COMMAND: "{:s}"'.format(str(options["cmd"]))
    for arg in options["args"]:
        temp += ' "{:s}"'.format(arg)
    out.append(temp)

    out.append("OUTPUT_FILES:")
    for outfile in sorted(LOGFILES):
        out.append(' "{:s}"'.format(outfile))

    def dump_str(name: str) -> None:
        val = options[CONFIG_OPTIONS[name][0]]
        if val is not None:
            out.append('{:s}: "{:s}"'.format(name, val))
        else:
            out.append("{:s}:".format(name))

    def dump_bool(name: str) -> None:
        out.append(
            '{:s}: "{:s}"'.format(
                name, "y" if options[CONFIG_OPTIONS[name][0]] else "n"
            )
        )

    dump_str("GAME")
    dump_bool("USE_GPU")
    dump_bool("FALLBACK")
    dump_bool("PRIMUS")
    dump_bool("VSYNC")
    dump_bool("HIDE_TOP_BAR")
    dump_bool("STOP_XCAPE")
    dump_str("PROC_NAME")
    dump_str("WINDOW_TITLE")
    dump_str("WINDOW_CLASS")

    return "\n".join(out)


class ConfigException(Exception):
    """
    An error caused by an invalid configuration file.
    """

    pass


def parse_config_file(data: str) -> ConfigDict:
    """
    Parses the contents of a configuration file.
    """

    def parse_option(option: str, value: Any) -> Tuple[str, Any]:
        if option not in CONFIG_OPTIONS:
            raise ConfigException("Invalid option: {}".format(option))
        dest, type_ = CONFIG_OPTIONS[option][:2]

        if type_ is str:
            vals = shlex.split(value)
            if len(vals) == 1:
                # strip quotes if there's only one string
                return dest, vals[0]
            return dest, value
        if type_ is list:
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
    options = CONFIG_DEFAULTS.copy()
    options["args"] = []
    for opt, val in config_p.items("section"):
        dest, value = parse_option(opt, val)
        options[dest] = value

    return options


def check_config(cfg: ConfigDict) -> Optional[str]:
    """
    Checks if a configuration is valid.

    Returns None if it is valid, or an error message if not.
    """
    # a command is required
    if not cfg["cmd"]:
        return "No command specified"

    # the command must be a valid executable
    if not cast(Path, cfg["cmd"]).is_file():
        return 'The file "{:s}" specified for command does not exist.'.format(
            str(cfg["cmd"])
        )
    if not os.access(cast(Path, cfg["cmd"]), os.X_OK):
        return 'The file "{:s}" specified for command is not executable.'.format(
            str(cfg["cmd"])
        )

    if cfg["stop_xcape"] and not (cfg["window_title"] or cfg["window_class"]):
        return "WINDOW_TITLE or WINDOW_CLASS must be given to use STOP_XCAPE"
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


def get_config(args: argparse.Namespace) -> ConfigDict:
    """
    Constructs a configuration from the given arguments.
    """
    # pylint: disable=redefined-outer-name
    config = CONFIG_DEFAULTS.copy()

    # order of configuration precedence, from highest to lowest:
    #  1. command line parameters (<command>, --hide-top-bar, --no-discrete)
    #  2. explicit configuration file (--configfile)
    #  3. game configuration file (--game)

    # parse game config file
    if args.game is not None:
        try:
            with open(WRAPPER_DIR / "config" / (args.game + ".cfg")) as file:
                config_data = file.read()
            config.update(parse_config_file(config_data))
        except OSError:
            if args.configfile is None:
                logger.error(
                    'The configuration file for "%s" was not found in %s.',
                    args.game,
                    WRAPPER_DIR / "config",
                )
                sys.exit(1)
        config["game"] = args.game

    # check for explicit config file
    if args.configfile is not None:
        config.update(parse_config_file(args.configfile.read()))

    if config["game"] is not None and config["logfile"] is None:
        config["logfile"] = WRAPPER_DIR / "logs" / (config["game"] + ".log")

    if config["logfile"] is not None:
        setup_logfile(config["logfile"])

    # check arguments
    if args.command is not None:
        # print('cli command:', args.command)
        if len(args.command) >= 1:
            config["cmd"] = Path(args.command[0]).absolute()
            config["args"] = args.command[1:]

    # override boolean options given on command line
    for props in CONFIG_OPTIONS.values():
        opt_name = props[0]
        if (
            props[1] == bool
            and opt_name in args
            and getattr(args, opt_name) is not None
        ):
            config[opt_name] = getattr(args, opt_name)

    return config


def construct_command_line(options: ConfigDict) -> Tuple[List[str], Dict[str, str]]:
    """
    Constructs a full command line and environment dict from a configuration
    """
    cmd_args: List[str] = []
    environ: Dict[str, str] = dict()
    # check if we're running under nvidia-xrun
    if os.environ.get("NVIDIA_XRUN") is not None:
        if not options["force_vsync"]:
            environ["__GL_SYNC_TO_VBLANK"] = "0"
    elif options["use_gpu"]:
        if options["use_primus"] and not options["force_vsync"]:
            environ["vblank_mode"] = "0"
        cmd_args.append("optirun")
        if logger.level == logging.DEBUG:
            cmd_args.append("--debug")
        if options["use_primus"]:
            cmd_args.extend("-b primus".split())
    cmd_args.append(str(options["cmd"]))
    if options["args"] is not None:
        cmd_args.extend(cast(List[str], options["args"]))
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
    n = notify2.Notification("optiwrapper", msg, icon)
    n.show()


class WrapperActions:
    """
    Holds callbacks for game management events.
    """

    def __init__(self, cfg: ConfigDict):
        self.hide_top_bar = cfg["hide_top_bar"]
        self.xcape_procs: List[Process] = list()
        if cfg["stop_xcape"]:
            self.xcape_procs = pgrep("xcape")

        self.logger = logging.getLogger("optiwrapper.action")

    def _try_pause_xcape(self) -> None:
        for xcape_proc in self.xcape_procs:
            xcape_proc.suspend()

    def _try_resume_xcape(self) -> None:
        for xcape_proc in self.xcape_procs:
            xcape_proc.resume()

    def start(self) -> None:
        """
        To be run when the game starts.
        """
        logger.debug("game starting...")
        log_time(Event.START)
        # hide top bar
        if self.hide_top_bar:
            gse.enable_extension("hidetopbar@mathieu.bidon.ca")

    def stop(self, killed: bool = False) -> None:
        """
        To be run after the game exits.
        """
        lib.running = False
        logger.debug("game stopped")
        if killed:
            log_time(Event.DIE)
        else:
            log_time(Event.STOP)
        # resume xcape
        self._try_resume_xcape()
        # unhide top bar
        if self.hide_top_bar:
            gse.disable_extension("hidetopbar@mathieu.bidon.ca")

    def focus(self) -> None:
        """
        To be run when the game window is focused.
        """
        logger.debug("window focused")
        if lib.running:
            log_time(Event.FOCUS)
        # pause xcape
        self._try_pause_xcape()

    def unfocus(self) -> None:
        """
        To be run when the game window loses focus.
        """
        logger.debug("window unfocused")
        if lib.running:
            log_time(Event.UNFOCUS)
        # resume xcape
        self._try_resume_xcape()


class FocusThread(threading.Thread):
    def __init__(self, cfg: ConfigDict):
        super().__init__()
        self.daemon = True
        self.kwargs: Dict[str, Union[bool, int, str]] = {"only_visible": True}
        if cfg["window_title"] is not None:
            self.kwargs["winname"] = cast(str, cfg["window_title"])
        if cfg["window_class"] is not None:
            self.kwargs["winclassname"] = "^" + cast(str, cfg["window_class"]) + "$"

    def run(self) -> None:
        # if a window is closed, search for new matching windows again
        closed_win = 1
        while closed_win > 0 and lib.running:
            xdo = myxdo.xdo_new(None)
            wins = search_windows(xdo, **self.kwargs)  # type: ignore
            window_start_time = time.time()
            while not wins and lib.running:
                if time.time() > window_start_time + WINDOW_WAIT_TIME:
                    logger.error("Window not found within {} seconds")
                    sys.exit(1)
                time.sleep(0.5)
                wins = search_windows(xdo, **self.kwargs)  # type: ignore
            myxdo.xdo_free(xdo)
            xdo = None
            logger.debug("found window(s): [%s]", ", ".join(map("0x{:x}".format, wins)))
            closed_win = watch_focus(  # type: ignore
                wins, lambda evt: actions.focus(), lambda evt: actions.unfocus()
            )
            time.sleep(0.1)


if __name__ == "__main__":
    # pylint: disable=invalid-name

    # create console log handler and set level to debug, as the actual level
    # selection is done in the logger
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("{levelname:.1s}:{name}: {message}", style="{"))
    logger.addHandler(ch)

    # initialize notification system
    notify2.init("optiwrapper")

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
        "-C",
        "--configfile",
        type=argparse.FileType("r"),
        metavar="FILE",
        help="use a specific configuration file",
    )
    parser.add_argument(
        "-G",
        "--game",
        metavar="GAME",
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

    config = get_config(args)

    cfg_err_msg = check_config(config)
    if cfg_err_msg is not None:
        logger.error(cfg_err_msg)
        sys.exit(1)

    # check if discrete GPU works, notify if not
    if (
        config["use_gpu"]
        and os.environ.get("NVIDIA_XRUN") is None
        and subprocess.run(["optirun", "--silent", "true"]).returncode != 0
    ):
        if config["fallback"]:
            notify(
                "Discrete GPU not working, falling back to integrated GPU",
                logging.ERROR,
                True,
            )
            config["use_gpu"] = False
        else:
            notify("Discrete GPU not working, quitting", logging.ERROR, True)
            sys.exit(1)

    if args.test:
        print(dump_test_config(config))
        sys.exit(0)

    logger.debug("\n%s", format_config(config))

    # setup time logging
    if config["game"] is not None:
        TIME_LOGFILE = WRAPPER_DIR / "time/{}.log".format(config["game"])
        # create directory if it doesn't exist
        TIME_LOGFILE.parent.mkdir(parents=True, exist_ok=True)

    # setup command
    command, env_override = construct_command_line(config)
    logger.debug("Command: %s", repr(command))

    actions = WrapperActions(config)

    # remove overlay library for wrong architecture
    if "LD_PRELOAD" in os.environ:
        if config["is_32_bit"]:
            bad_lib = "ubuntu12_64"
        else:
            bad_lib = "ubuntu12_32"
        env_override["LD_PRELOAD"] = ":".join(
            lib for lib in os.environ["LD_PRELOAD"].split(":") if bad_lib not in lib
        )
        logger.debug('Fixed LD_PRELOAD: now "%s"', env_override["LD_PRELOAD"])

    def cb_signal_handler(signum, frame):
        """
        Write a message to both logs, then die.
        """
        actions.stop(killed=True)
        atexit.unregister(actions.stop)
        logger.error("Killed by external signal %d", signum)
        sys.exit(1)

    # clean up when killed by a signal
    signal.signal(signal.SIGTERM, cb_signal_handler)
    signal.signal(signal.SIGINT, cb_signal_handler)
    atexit.register(actions.stop)
    actions.start()

    # run command
    proc = subprocess.Popen(command, env={**os.environ, **env_override})
    if config["window_class"] is not None or config["window_title"] is not None:
        ft = FocusThread(config)
        ft.start()

    if config["proc_name"] is None:
        # just wait for subprocess to finish
        proc.wait()
        logger.debug("subprocess %d done, exiting wrapper", proc.pid)
    else:
        # find process
        time.sleep(2)
        pattern = cast(str, config["proc_name"])
        proc_start_time = time.time()
        procs = pgrep(pattern)
        logger.debug("found: %s", procs)
        while len(procs) != 1:
            if time.time() > proc_start_time + PROCESS_WAIT_TIME:
                logger.error("Process not found within {} seconds")
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
