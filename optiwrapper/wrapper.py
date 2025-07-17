"""
Wrapper script to run games with Optimus, turn off xcape while focused, log
playtime, and more.
"""


import argparse
import asyncio
import enum
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    NoReturn,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import arrow
import dbus_next
import desktop_notify
import pyprctl

from optiwrapper import hooks, lib
from optiwrapper.lib import SETTINGS_DIR, WRAPPER_DIR, logger, pgrep, watch_focus
from optiwrapper.libxdo import xdo_free, xdo_new, xdo_search_windows
from optiwrapper.settings import Config


class GpuType(enum.Enum):
    UNKNOWN = enum.auto()
    INTEL = enum.auto()
    # INTEL_NOUVEAU = enum.auto()
    NVIDIA = enum.auto()
    BUMBLEBEE = enum.auto()
    PRIME = enum.auto()


class ExitCode(enum.Enum):
    SUCCESS = 0
    KILLED = 1
    NO_GPU = 2
    NO_GAME_WINDOW = 3
    NO_GAME_PROCESS = 4
    MULTIPLE_GAME_PROCESSES = 5


# constants
WINDOW_WAIT_TIME = 120
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


pyprctl.set_child_subreaper(True)


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
    START = enum.auto()
    STOP = enum.auto()
    UNFOCUS = enum.auto()
    FOCUS = enum.auto()
    DIE = enum.auto()


def get_gpu_type(needs_gpu: bool) -> GpuType:
    # construct_command_line
    if os.environ.get("NVIDIA_XRUN") is not None:
        return GpuType.NVIDIA
    if (
        os.readlink("/etc/X11/xorg.conf.d/20-dgpu.conf")
        == "/etc/X11/video/20-nvidia.conf"
    ):
        return GpuType.PRIME

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


def construct_command_line(
    config: Config, gpu_type: GpuType
) -> Tuple[List[str], Dict[str, str]]:
    """
    Constructs a full command line and environment dict from a configuration
    """
    cmd_args: List[str] = []
    environ: Dict[str, str] = {}
    if not config.flags.vsync:
        if gpu_type is GpuType.NVIDIA or (
            gpu_type is GpuType.PRIME and config.flags.use_gpu
        ):
            environ["__GL_SYNC_TO_VBLANK"] = "0"
        else:
            environ["vblank_mode"] = "0"
    if config.flags.use_gpu:
        vk_icd_filenames = ["nvidia_icd.json"]
        if gpu_type is GpuType.PRIME:
            cmd_args.append("prime-run")
        elif gpu_type is GpuType.BUMBLEBEE:
            cmd_args.append("optirun")
            if logger.isEnabledFor(logging.DEBUG):
                cmd_args.append("--debug")
            if config.flags.use_primus:
                cmd_args.extend("-b primus".split())
    else:
        vk_icd_filenames = [
            "radeon_icd.x86_64.json",
            "radeon_icd.i686.json",
            # "radeon_icd.{}.json".format("x86_64" if config.flags.is_64_bit else "i686"),
            # "intel_icd.x86_64.json",
            # "intel_hasvk_icd.x86_64.json",
        ]
    environ["VK_ICD_FILENAMES"] = ":".join(
        "/usr/share/vulkan/icd.d/" + filename for filename in vk_icd_filenames
    )
    if config.command:
        cmd_args.extend(config.command)
    return cmd_args, environ


async def notify(msg: str, level: int = logging.INFO, log: bool = False) -> None:
    icon = {
        logging.INFO: "dialog-information",
        logging.WARNING: "dialog-warning",
        logging.ERROR: "dialog-error",
    }.get(level, "dialog-information")
    if log:
        logger.log(level, msg)
    try:
        server = desktop_notify.aio.Server("optiwrapper")
        notification = server.Notify("optiwrapper", msg, icon)
        await notification.show()
    except dbus_next.DBusError:
        logger.exception("Displaying notification failed")


_BACKGROUND_TASKS = set()

_T = TypeVar("_T")


def create_background_task(
    coro: Coroutine[Any, Any, _T], *, name: Optional[str] = None
) -> asyncio.Task[_T]:
    task = asyncio.create_task(coro, name=name)
    # Add task to the set. This creates a strong reference.
    _BACKGROUND_TASKS.add(task)
    # To prevent keeping references to finished tasks forever,
    # make each task remove its own reference from the set after
    # completion:
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


class FocusThread(threading.Thread):
    def __init__(self, main: "Main", loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.main = main
        self.loop = loop
        self.daemon = True
        self.kwargs: Dict[str, Union[bool, int, str]] = {
            "only_visible": True,
            "require_all": True,  # require all conditions to match
        }

        self.track_focus = False
        if main.cfg.window_title:
            self.kwargs["winname"] = main.cfg.window_title
            self.track_focus = True
        if main.cfg.window_class:
            self.kwargs["winclassname"] = "^(" + main.cfg.window_class + ")$"
            self.track_focus = True

        self.in_window_manager = bool(main.window_manager)
        if not self.in_window_manager:
            logger.debug("not in WM")

    def call_handler(self, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self.loop.call_soon_threadsafe(create_background_task, handler(arrow.now()))

    def run(self) -> None:
        if not self.track_focus:
            return
        if not self.in_window_manager:
            self.call_handler(self.main.focused)
            return
        logger.debug("in WM, tracking focus")

        # if a window is closed, search for new matching windows again
        closed_win = 1
        logger.debug("waiting for window...")
        while closed_win > 0 and lib.running:
            xdo = xdo_new(None)
            wins = xdo_search_windows(xdo, **self.kwargs)  # type: ignore[arg-type]
            window_start_time = time.time()
            while not wins and lib.running:
                if time.time() > window_start_time + WINDOW_WAIT_TIME:
                    self.loop.call_soon_threadsafe(
                        create_background_task,
                        notify(
                            f"Window not found within {WINDOW_WAIT_TIME} seconds",
                            logging.ERROR,
                            log=True,
                        ),
                    )
                    self.loop.call_soon_threadsafe(
                        self.main.trigger_exit, ExitCode.NO_GAME_WINDOW
                    )
                    return
                time.sleep(0.1)
                wins = xdo_search_windows(xdo, **self.kwargs)  # type: ignore[arg-type]
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
                    lambda evt: self.call_handler(self.main.focused),
                    lambda evt: self.call_handler(self.main.unfocused),
                )
            )
            logger.debug("watch_focus returned %x", closed_win)
            time.sleep(0.1)
        if closed_win <= 0:
            logger.debug("window closed")


class Main:  # pylint: disable=too-many-instance-attributes
    cfg: Config
    gpu_type: GpuType
    time_logfile: Path
    window_manager: str
    command: List[str]
    env_override: Dict[str, str]
    exit_code: ExitCode
    stop_event: asyncio.Event
    subprocess_task: Optional[asyncio.Task[int]]

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

        self.gpu_type = get_gpu_type(needs_gpu=self.cfg.flags.use_gpu)
        logger.debug("GPU: %s", self.gpu_type)

        # setup time logging
        self.time_logfile = WRAPPER_DIR / f"time/{self.cfg.game}.log"
        # create directory if it doesn't exist
        self.time_logfile.parent.mkdir(parents=True, exist_ok=True)

        # check if we're in a WM
        wmctrl_proc = subprocess.run(
            ["wmctrl", "-m"],
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            self.window_manager = wmctrl_proc.stdout.splitlines()[0].partition(": ")[2]
        except IndexError:
            self.window_manager = ""

        self.command = []
        self.env_override = {}
        self.exit_code = ExitCode.SUCCESS
        self.stop_event = asyncio.Event()
        self.subprocess_task = None

    async def finish_setup(self) -> None:
        # check if discrete GPU works, notify if not
        if self.cfg.flags.use_gpu and self.gpu_type not in (
            GpuType.NVIDIA,
            GpuType.BUMBLEBEE,
            GpuType.PRIME,
        ):
            if self.cfg.flags.fallback:
                await notify(
                    "Discrete GPU not working, falling back to integrated GPU",
                    logging.ERROR,
                    True,
                )
                self.cfg.flags.use_gpu = False
            else:
                await notify("Discrete GPU not working, quitting", logging.ERROR, True)
                self.trigger_exit(ExitCode.NO_GPU)
                return

        # if args.test:
        #     print(dump_test_config(cfg))
        #     sys.exit(0)

        logger.debug("\n%s", self.cfg.pretty())

        # load hooks
        hooks.register_hooks()
        for hook_name in self.cfg.hooks:
            await hooks.load_hook(
                hook_name,
                cfg=self.cfg,
                gpu_type=self.gpu_type,
                window_manager=self.window_manager,
            )

        # setup command
        self.command, self.env_override = construct_command_line(
            self.cfg, self.gpu_type
        )
        logger.debug("Command: %s", repr(self.command))

        # remove overlay library for wrong architecture and disable screensaver fix
        self.env_override.update(lib.clean_ld_preload(self.cfg.flags.is_64_bit))
        if "LD_PRELOAD" in self.env_override:
            logger.debug('Fixed LD_PRELOAD: now "%s"', self.env_override["LD_PRELOAD"])

        logger.debug(
            "env vars: %s",
            " ".join(k + "=" + v for k, v in self.env_override.items()),
        )
        logger.debug("CWD: %s", Path().absolute())
        logger.debug(
            "LD_LIBRARY_PATH: %s",
            self.env_override.get(
                "LD_LIBRARY_PATH", os.environ.get("LD_LIBRARY_PATH", "")
            ),
        )
        if self.cfg.game == "Minecraft" and "INST_NAME" in os.environ:
            logger.debug(
                "PrismLauncher instance: %s (ID=%r)",
                os.environ["INST_NAME"],
                os.environ["INST_ID"],
            )

    async def run(self) -> None:
        await self.finish_setup()
        if self.stop_event.is_set():
            return

        async def cb_signal_handler(signame: str) -> None:
            """
            Write a message to both logs, then die.
            """
            logger.error("Killed by external signal %s", signame)
            await self.stopped(killed=True)
            self.trigger_exit(ExitCode.KILLED)

        # clean up when killed by a signal
        loop = asyncio.get_event_loop()
        for signame in ("SIGINT", "SIGTERM"):
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda signame=signame: create_background_task(
                    cb_signal_handler(signame)
                ),
            )

        await self.started()
        try:
            await self._run_game()
            if self.subprocess_task is not None:
                self.subprocess_task.cancel()
            if lib.running:
                await self.stopped()
            # finish all pending background tasks
            await asyncio.gather(
                *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
            )
        finally:
            # try to make sure we write a stop event to the time log
            if lib.running:
                await self.stopped()

    # pylint 2.17.4 says asyncio.subprocess.Process doesn't exist
    async def wait_for_process(self, process: "asyncio.subprocess.Process") -> int:
        logger.debug("waiting on subprocess %d", process.pid)
        returncode = await process.wait()
        logger.debug(
            "subprocess %d exited with return code %d; exiting wrapper",
            process.pid,
            returncode,
        )
        self.trigger_exit(ExitCode.SUCCESS)
        return returncode

    async def find_process(
        self, launcher: "asyncio.subprocess.Process", loop: asyncio.AbstractEventLoop
    ) -> int:
        # wait on the launcher process in the background, to avoid zombies
        launcher_task = create_background_task(launcher.wait())
        # find process by name
        pattern = self.cfg.process_name
        proc_start_time = time.time()
        procs: List[lib.Process] = []
        while len(procs) != 1:
            if time.time() > proc_start_time + PROCESS_WAIT_TIME:
                logger.error("Process not found within %d seconds", PROCESS_WAIT_TIME)
                self.trigger_exit(ExitCode.NO_GAME_PROCESS)
                create_background_task(
                    notify("Failed to find game PID, quitting", logging.ERROR)
                )
                self.subprocess_task = launcher_task
                return -1
            procs = await asyncio.to_thread(pgrep, pattern)
            logger.debug("found: %s", procs)
            if len(procs) > 1:
                logger.error("Multiple matching processes:")
                for p in procs:
                    logger.error("%s", p)
                self.trigger_exit(ExitCode.MULTIPLE_GAME_PROCESSES)
                self.subprocess_task = launcher_task
                return -1
            await asyncio.sleep(0.5)

        watcher = asyncio.PidfdChildWatcher()
        watcher.attach_loop(loop)

        process_fut: asyncio.Future[int] = loop.create_future()

        # found single process to wait for
        logger.debug("waiting on process %d", procs[0].pid)
        watcher.add_child_handler(
            procs[0].pid,
            lambda pid, returncode: process_fut.set_result(returncode),
        )

        # wait for the game process to exit
        returncode = await process_fut
        logger.debug("process %d exited with return code %d", procs[0].pid, returncode)
        self.trigger_exit(ExitCode.SUCCESS)
        return returncode

    async def _run_game(self) -> None:
        loop = asyncio.get_event_loop()
        # track focus
        ft = FocusThread(self, loop)
        ft.start()

        # run command
        proc = await asyncio.create_subprocess_exec(
            self.command[0],
            *self.command[1:],
            env={**os.environ, **self.env_override},
        )

        if not self.cfg.process_name:
            # just wait for subprocess to finish
            self.subprocess_task = create_background_task(self.wait_for_process(proc))
        else:
            # find main game process and wait for it to finish
            self.subprocess_task = create_background_task(self.find_process(proc, loop))

        # the stop event will be set by one of the subprocess callbacks or by
        # an error handler
        await self.stop_event.wait()

    ##################
    # event handlers #
    ##################

    def trigger_exit(self, exit_code: ExitCode) -> None:
        if not self.stop_event.is_set():
            self.stop_event.set()
            self.exit_code = exit_code

    def log_time(self, event: Event, dt: Optional[arrow.Arrow] = None) -> None:
        """
        Writes a message to the time logfile, if one exists.
        """
        if dt is None:
            dt = arrow.now()
        message = {
            Event.START: "game started",
            Event.STOP: "game stopped",
            Event.UNFOCUS: "user left",
            Event.FOCUS: "user returned",
            Event.DIE: "wrapper died",
        }[event]

        if self.cfg.game == "Minecraft" and "INST_ID" in os.environ:
            message += f" (instance: {os.environ['INST_ID']})"

        timestamp = dt.format("YYYY-MM-DDTHH:mm:ss.SSSZZ")
        with open(self.time_logfile, "a") as logfile:
            logfile.write(f"{timestamp}: {message}\n")

    async def started(self, dt: Optional[arrow.Arrow] = None) -> None:
        """
        To be run when the game starts.
        """
        logger.debug("game starting...")
        self.log_time(Event.START, dt)
        for hook in hooks.get_loaded_hooks().values():
            await hook.on_start()

    async def stopped(
        self, dt: Optional[arrow.Arrow] = None, killed: bool = False
    ) -> None:
        """
        To be run after the game exits.
        """
        lib.running = False
        logger.debug("game stopped")
        if killed:
            self.log_time(Event.DIE, dt)
        else:
            self.log_time(Event.STOP, dt)
        for hook in hooks.get_loaded_hooks().values():
            await hook.on_stop()

    async def focused(self, dt: Optional[arrow.Arrow] = None) -> None:
        """
        To be run when the game window is focused.
        """
        logger.debug("window focused")
        if lib.running:
            self.log_time(Event.FOCUS, dt)
        for hook in hooks.get_loaded_hooks().values():
            await hook.on_focus()

    async def unfocused(self, dt: Optional[arrow.Arrow] = None) -> None:
        """
        To be run when the game window loses focus.
        """
        logger.debug("window unfocused")
        if lib.running:
            self.log_time(Event.UNFOCUS, dt)
        for hook in hooks.get_loaded_hooks().values():
            await hook.on_unfocus()


@dataclass(init=False)
class _Arguments:  # pylint: disable=too-many-instance-attributes
    help: Optional[str]
    command: List[str]
    game: str
    hide_top_bar: Optional[bool]
    debug: bool
    quiet: bool
    use_gpu: Optional[bool]
    outfile: str
    classname: str
    test: bool


def parse_args() -> _Arguments:
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
        "-d",
        "--debug",
        help="enable debugging output",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help="disable debugging output",
        dest="debug",
        action="store_false",
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

    args = parser.parse_args(namespace=_Arguments())

    if args.help == "config":
        print(CONFIG_HELP)
        sys.exit(0)
    elif args.help is not None:
        parser.print_help()
        sys.exit(0)

    if args.game is None:
        parser.error("the following arguments are required: -G/--game")

    return args


def get_config(args: _Arguments) -> Config:
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
            SETTINGS_DIR,
        )
        sys.exit(1)

    setup_logfile(WRAPPER_DIR / "logs" / f"{config.game}.log")

    # check arguments
    if args.command:
        # print('cli command:', args.command)
        if config.command and config.command[0] != args.command[0]:
            logger.warning("Different command given in config file and command line")
        config.command = args.command

    if args.use_gpu is not None:
        config.flags.use_gpu = args.use_gpu

    if args.hide_top_bar is not None:
        if "hide_top_bar" not in config.hooks:
            config.hooks.append("hide_top_bar")

    return config


def run() -> NoReturn:
    # create console log handler and set level to debug, as the actual level
    # selection is done in the logger
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("{levelname:.1s}:{name}: {message}", style="{"))
    logger.addHandler(ch)

    args = parse_args()
    # print(args)

    # setup logging
    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.outfile is not None:
        setup_logfile(args.outfile)

    cfg = get_config(args)

    cfg_err_msg = cfg.check()
    if cfg_err_msg is not None:
        logger.error(cfg_err_msg)
        sys.exit(1)

    main = Main(cfg)

    asyncio.run(main.run())
    sys.exit(main.exit_code.value)
