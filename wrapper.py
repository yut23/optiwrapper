#!/usr/bin/env python3
"""
Wrapper script to run games with Optimus, turn off xcape while focused, log
playtime, and more.
"""

import argparse
import configparser
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union, cast

from lib import myxdo, search_windows, watch_focus

ConfigDict = Mapping[str, Union[None, str, List[str], bool, Path]]


# logging

logger = logging.getLogger("optiwrapper")  # pylint: disable=invalid-name
logger.setLevel(logging.WARN)
logger.propagate = False
LOGFILE_FORMATTER = logging.Formatter(
    "{asctime:s} |{levelname:^10s}| {message:s}", style="{"
)
LOGFILES: Set[str] = set()


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

VSYNC [n]: Whether to run primus with vblank_mode=0

HIDE_TOP_BAR [n]: Whether to hide the top bar when the game is run.

PROC_NAME: The process name, for tracking when the game has exited. Only needed
  if the initial process isn't the same as the actual game (e.g. a launcher)

STOP_XCAPE [n]: Whether to disable xcape while the game is focused.
  Requires WINDOW_NAME or WINDOW_CLASS to be specified.

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
    "VSYNC": ("force_vsync", bool, False),
    "HIDE_TOP_BAR": ("hide_top_bar", bool, False),
    "STOP_XCAPE": ("stop_xcape", bool, False),
    "PROC_NAME": ("proc_name", str, None),
    "WINDOW_TITLE": ("window_title", str, None),
    "WINDOW_CLASS": ("window_class", str, None),
}

CONFIG_DEFAULTS: Dict[str, Any] = {
    dest: default for dest, type_, default in CONFIG_OPTIONS.values()
}


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
    dump_str("WINDOW_NAME")
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
            if not (value.startswith("(") and value.endswith(")")):
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

    # parse game config file, then explicit configuration file, then arguments
    if args.game is not None:
        try:
            with open(WRAPPER_DIR / "config" / (args.game + ".cfg")) as file:
                config_data = file.read()
        except OSError:
            logger.error(
                'The configuration file for "%s" was not found in %s.',
                args.game,
                WRAPPER_DIR / "config",
            )
            sys.exit(1)
        config.update(parse_config_file(config_data))
        config["game"] = args.game

    # check for explicit config file
    if args.configfile is not None:
        config.update(parse_config_file(args.configfile.read()))

    if config["game"] is not None and config["logfile"] is None:
        config["logfile"] = WRAPPER_DIR / "logs" / (config["game"] + ".log")

    if config["logfile"] is not None:
        setup_logfile(config["logfile"])

    # command
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


def construct_command_line(options: ConfigDict) -> List[str]:
    """
    Constructs a full command line from a configuration
    """
    cmd_args: List[str] = []
    if not options["use_gpu"]:
        return cmd_args
    if options["use_primus"] and not options["force_vsync"]:
        cmd_args.extend("env vblank_mode=0".split())
    cmd_args.append("optirun")
    if logger.level == logging.DEBUG:
        cmd_args.append("--debug")
    if options["use_primus"]:
        cmd_args.extend("-b primus".split())
    cmd_args.append(str(options["cmd"]))
    if options["args"] is not None:
        cmd_args.extend(cast(List[str], options["args"]))
    return cmd_args


if __name__ == "__main__":
    # pylint: disable=invalid-name

    # xTODO: remove this when done debugging in ipython
    # for h in list(logger.handlers):
    #     logger.removeHandler(h)

    # create console log handler and set level to debug, as the actual level
    # selection is done in the logger
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("{levelname}: {message}", style="{"))
    logger.addHandler(ch)

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
        "-C", "--configfile", metavar="FILE", help="use a specific configuration file"
    )
    parser.add_argument(
        "-G",
        "--game",
        metavar="GAME",
        help=("specify a game " "(will search for a config file)"),
    )
    parser.add_argument(
        "-f",
        "--hide-top-bar",
        help=("hide the top bar " "(needed for fullscreen in some games)"),
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
        help=("log all output to a file " "(will overwrite, not append)"),
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

    # order of configuration precedence, from highest to lowest:
    #  1. command line parameters (<command>, --hide-top-bar, --no-discrete)
    #  2. explicit configuration file (--configfile)
    #  3. game configuration file (--game)

    config = get_config(args)

    cfg_err_msg = check_config(config)
    if cfg_err_msg is not None:
        logger.error(cfg_err_msg)
        sys.exit(1)

    if args.test:
        print(dump_test_config(config))
        sys.exit(0)

    print(args.use_gpu)

    logger.debug("\n%s", format_config(config))

    # run command
    command = construct_command_line(config)
    logger.debug("Command: %s", repr(command))

    # xcape_pid = int(subprocess.run('pgrep xcape'.split(), capture_output=True).stdout)
    # print('Pausing xcape...')
    # os.kill(xcape_pid, signal.SIGSTOP)
    # input()
    # print('Resuming xcape...')
    # os.kill(xcape_pid, signal.SIGCONT)

    """
    Now that we have arguments, we need to do the actual wrapper stuff.
    if proc_name:
        watch for... fork? opening a new window?
    else:
        find window
    """

    proc = subprocess.Popen(command)
    if "window_class" in config or "window_title" in config:
        kwargs: Dict[str, Union[bool, int, str]] = {"only_visible": True}
        if "window_title" in config:
            kwargs["winname"] = cast(str, config["window_title"])
        if "window_class" in config:
            kwargs["winclassname"] = "^" + cast(str, config["window_class"]) + "$"
        xdo = myxdo.xdo_new(None)
        wins = search_windows(xdo, **kwargs)  # type: ignore
        while not wins:
            time.sleep(0.5)
            wins = search_windows(xdo, **kwargs)  # type: ignore
        myxdo.xdo_free(xdo)
        logger.debug("found window(s): %s", str(wins))
        focus_thread = threading.Thread(
            target=watch_focus, daemon=True, args=(wins, print, print)
        )
        focus_thread.start()
    proc.wait()
