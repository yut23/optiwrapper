#!/bin/bash
set -eu

declare -a OUTPUT_FILES

GAMES_DIR=~/Games
WRAPPER_DIR=$GAMES_DIR/wrapper

ARGS=()
USE_GPU=y
FALLBACK=y
PRIMUS=y
VSYNC=n
HIDE_TOP_BAR=n
STOP_XCAPE=n
DEBUG=

TEST=n

print_usage() {
  cat <<EOS
Usage: $(basename "$0") [OPTIONS] COMMAND

Options:
  -C --configfile FILE  use a specific configuration file
  -G --game GAME        specify a game (will search for a config file)
  -f --hide-top-bar     hide the top bar (needed for fullscreen in some games)
  -d --debug            enable debugging output (also -v, --verbose)
  -h --help             print this help message
  -n --no-discrete      don't use discrete graphics
  -o --output FILE      log all output to a file (will overwrite, not append)
     --                 stop processing options

Game-specific configuration (command to run, whether to use primus, etc) should
be put in ./<GAME>.cfg, relative to this script's location. Run with "-h config"
for more information.

Examples:
  With a configuration file: $(basename "$0") -G Infinifactory
  For a Steam game: $(basename "$0") %command%
EOS
}

print_config_help() {
  cat <<EOS
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
  Requires WINDOW_TITLE or WINDOW_CLASS to be specified.

WINDOW_TITLE: Name of main game window (can use bash regular expressions)

WINDOW_CLASS: Class name of main game window (must match exactly). Can be
  found by looking at the first string returned by "xprop WM_CLASS".
EOS
}

log() {
  echo "$@"
  for f in "${OUTPUT_FILES[@]}"; do
    echo "$@" >> "$f"
  done
}

debug() {
  [ -n "$DEBUG" ] && log "$@"
  return 0
}

error() {
  if [[ $1 == --notify ]]; then
    shift
    notify --error "$@"
  fi
  >&2 log -n "ERROR: "
  >&2 log "$@"
}

notify() {
  icon=dialog-information
  case $1 in
    --error)
      icon=dialog-error
      shift
      ;;
    --warn*)
      icon=dialog-warning
      shift
      ;;
    --info*)
      icon=dialog-information
      shift
      ;;
  esac
  notify-send -i "$icon" "optiwrapper" "$@"
}

log_time() {
  # ISO-8601 format; local time with milliseconds
  datetime=$(date +'%FT%T.%3N%:z')
  # make sure TIME_LOGFILE is set
  if [[ -z "${TIME_LOGFILE:-}" ]]; then
    return
  fi
  case $1 in
    START)
      message="game started"
      ;;
    STOP)
      message="game stopped"
      ;;
    UNFOCUSED)
      message="user left"
      ;;
    FOCUSED)
      message="user returned"
      ;;
    DIED)
      message="wrapper died"
      ;;
    *)
      message="unknown"
      error "Unknown argument to log_time: $1"
      ;;
  esac
  echo "$datetime: $message" >> "$TIME_LOGFILE"
}

is_absolute() {
  [[ "${1:0:1}" == / || "${1:0:2}" == ~[/a-zA-Z] ]]
}

check_args() {
  if [[ $2 -lt ${3-2} ]] ; then
    error "An argument is required for the $1 option."
    exit 1
  fi
}

check_file() {
  if [[ ! -e "$2" ]] ; then
    error "The $1 file \"$2\" does not exist."
    exit 1
  fi
}

setup_output_file() {
  out_file="$1"
  debug "using output file: $out_file"
  out_dir=$(dirname "$out_file")
  if [[ ! -e "$out_dir" ]] ; then
    if ! mkdir -p "$out_dir" ; then
      error "Could not create directory \"$out_dir\" for output file."
      exit 1
    fi
  fi
  if [[ ! -d "$out_dir" ]] ; then
    error "Specified directory \"$out_dir\" (for output file \"$out_file\") is not valid."
    exit 1
  fi
  true > "$out_file"
  out_file=$(readlink -e "$out_file")

  # only add file to array if it's not already there
  if [[ ! " ${OUTPUT_FILES[*]} " == *" ${out_file} "* ]]; then
    OUTPUT_FILES+=("$out_file")
  fi
}


# get script location
#DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# option handling
while [[ $# -gt 0 ]]; do

case "$1" in
  #-c|--command)
  #  check_args "--command" $#
  #  CMD="$2"
  #  debug "explicit command: $CMD"
  #  shift
  #  ;;
  -C|--configfile)
    check_args "--configfile" $#
    CONFIG_FILE="$2"
    debug "explicit config file: $CONFIG_FILE"
    shift
    ;;
  -d|--debug|-v|--verbose)
    DEBUG=y
    debug "debugging output enabled"
    ;;
  -G|--game)
    check_args "--game" $#
    GAME="$2"
    if [[ -e $WRAPPER_DIR/config/$GAME.cfg ]] ; then
      CONFIG_FILE="$WRAPPER_DIR/config/$GAME.cfg"
    elif [[ -z ${CONFIG_FILE+x} ]]; then
      error "The configuration file for \"$GAME\" was not found in $WRAPPER_DIR/config/."
      exit 1
    fi
    debug "game specified: $GAME"
    shift
    ;;
  -f|--hide-top-bar)
    HIDE_TOP_BAR=y
    debug "hiding top bar"
    ;;
  -h|--help|--usage)
    if [[ $# -ge 2 && $2 == "config" ]] ; then
      print_config_help
    else
      print_usage
    fi
    exit 0
    ;;
  -n|--no-discrete)
    USE_GPU=n
    debug "not using discrete GPU"
    ;;
  -o|--output)
    check_args "--output" $#
    setup_output_file "$2"
    shift
    ;;
  -t|--test)
    TEST=y
    debug "enabling test mode"
    ;;
  --)
    break
    ;;
  -*)
    echo "ERROR: Unrecognized option: $1"
    echo "Call with --help for brief description of options"
    exit 1
    ;;
  *)
    # game command line
    break
    ;;
esac
shift
done


if [[ -n "${CONFIG_FILE:+x}" ]] ; then
  check_file "configuration" "$CONFIG_FILE"
  # shellcheck disable=SC1090
  # I should probably do this in a more secure way, but it works for now.
  source "$CONFIG_FILE"
  debug "configuration loaded from $CONFIG_FILE"
fi

# make sure a command was specified, either on the command line or in a config file
if [[ -z ${CMD:+x} ]] ; then
  if [[ $# -eq 0 ]] ; then
    error "A command must be specified."
    >&2 print_usage
    exit 1
  fi

  # if command was not in config file, then use the rest of the command line
  CMD=$1
  shift
  ARGS=("$@")
fi


# try to canonicalize relative executable paths
if ! is_absolute "$CMD" ; then
  CMD="$PWD/$CMD"
fi

# ensure $CMD exists
check_file "executable" "$CMD"


# setup log file
if [[ -z ${LOGFILE+x} ]] ; then
  # LOGFILE is unset (and not empty)
  mkdir -p "$WRAPPER_DIR/logs"
  if [[ -n ${GAME:+x} ]] ; then
    debug "using log file constructed from game name: $GAME.log"
    LOGFILE="$WRAPPER_DIR/logs/$GAME.log"
  elif [[ -n ${CONFIG_FILE:+x} ]] ; then
    # get config file name
    config_file_name=$(basename "$CONFIG_FILE")
    debug "using log file constructed from config file name: ${config_file_name%.*}.log"
    LOGFILE="$WRAPPER_DIR/logs/${config_file_name%.*}.log"
  fi
fi
if [[ -n ${LOGFILE+x} ]] ; then
  # LOGFILE is not empty
  setup_output_file "$LOGFILE"
fi

# setup playtime logging
if [[ -n ${GAME:+x} ]] ; then
  mkdir -p "$WRAPPER_DIR/time"
  TIME_LOGFILE="$WRAPPER_DIR/time/$GAME.log"
fi


optirun_cmd() {
  if [[ $USE_GPU == n || -n ${NVIDIA_XRUN:+x} ]] ; then
    return
  fi
  if [[ $PRIMUS == y ]] && [[ $VSYNC == n ]] ; then
    printf "env vblank_mode=0 "
  fi
  printf "optirun"
  if [[ -n $DEBUG ]] ; then
    printf -- " --debug"
  fi
  if [[ $PRIMUS == y ]] ; then
    printf -- " -b primus"
  fi
}

if [[ -n "${LD_PRELOAD+x}" ]]; then
  export LD_PRELOAD=${LD_PRELOAD/\/home\/eric\/.local\/share\/Steam\/ubuntu12_32\/gameoverlayrenderer.so/}
  LD_PRELOAD=${LD_PRELOAD/::/:/}
  debug "Fixed LD_PRELOAD: $LD_PRELOAD"
fi

OPTIRUN=$(optirun_cmd)
debug "full command: $OPTIRUN \"${CMD}\" ${ARGS[*]}"

# check if discrete GPU works
if [[ -z "${NVIDIA_XRUN:+x}" && $USE_GPU == y ]] && ! optirun --silent true; then
  if [[ $FALLBACK == y ]]; then
    error --notify "Discrete GPU not working, falling back to integrated GPU"
    USE_GPU=n
    OPTIRUN=
  else
    error --notify "Discrete GPU not working, quitting"
    exit 1
  fi
fi

try_pause_xcape() {
  if [[ $STOP_XCAPE == y ]]; then
    pkill -x -STOP xcape || true
  fi
}

try_resume_xcape() {
  if [[ $STOP_XCAPE == y ]]; then
    pkill -x -CONT xcape || true
  fi
}

wrapper_setup() {
  debug "game starting..."
  log_time START
  if [[ $HIDE_TOP_BAR == y ]]; then
    gnome-shell-extension-tool -e hidetopbar@mathieu.bidon.ca
  fi
  return 0
}

wrapper_teardown() {
  debug "game stopped"
  log_time STOP
  try_resume_xcape
  if [[ $HIDE_TOP_BAR == y ]]; then
    sleep 1
    gnome-shell-extension-tool -d hidetopbar@mathieu.bidon.ca
  fi
  return 0
}

if [[ -n ${WINDOW_TITLE:+x} || -n ${WINDOW_CLASS:+x} ]]; then
  CAN_TRACK_FOCUS=y
  #is_focused() {
  #  local winid focused_name
  #  if [[ -n ${WINDOW_CLASS:+x} ]]; then
  #    winid=$(xdotool getwindowfocus)
  #    focused_name=$(xprop -id "$winid" 8s '\t$0' WM_CLASS | cut -f2 | sed 's/^"\(.*\)"$/\1/')
  #    [[ $focused_name == "$WINDOW_CLASS" ]]
  #  else
  #    shopt -s nocasematch
  #    focused_name=$(xdotool getwindowfocus getwindowname)
  #    [[ $focused_name =~ $WINDOW_TITLE ]]
  #  fi
  #}
else
  CAN_TRACK_FOCUS=n
fi

if [[ ${TEST:-n} == y ]]; then
  printf 'COMMAND: "%s"' "$CMD"
  for arg in "${ARGS[@]}"; do
    printf ' "%s"' "$arg"
  done
  printf '\n'

  printf 'OUTPUT_FILES:\n'
  for file in "${OUTPUT_FILES[@]}"; do
    printf ' "%s"\n' "$file"
  done | sort

  printf 'GAME:'
  [[ -n ${GAME:+x} ]] && printf ' "%s"' "$GAME"
  printf '\n'
  printf 'USE_GPU: "%s"\n' "$USE_GPU"
  printf 'FALLBACK: "%s"\n' "$FALLBACK"
  printf 'PRIMUS: "%s"\n' "$PRIMUS"
  printf 'VSYNC: "%s"\n' "$VSYNC"
  printf 'HIDE_TOP_BAR: "%s"\n' "$HIDE_TOP_BAR"
  printf 'STOP_XCAPE: "%s"\n' "$STOP_XCAPE"
  printf 'PROC_NAME:'
  [[ -n ${PROC_NAME:+x} ]] && printf ' "%s"' "$PROC_NAME"
  printf '\n'
  printf 'WINDOW_TITLE:'
  [[ -n ${WINDOW_TITLE:+x} ]] && printf ' "%s"' "$WINDOW_TITLE"
  printf '\n'
  printf 'WINDOW_CLASS:'
  [[ -n ${WINDOW_CLASS:+x} ]] && printf ' "%s"' "$WINDOW_CLASS"
  printf '\n'
  exit 0
fi

# run setup now and set teardown to run on exit
wrapper_setup && trap wrapper_teardown INT TERM EXIT

if [[ $CAN_TRACK_FOCUS == y ]] ; then
  if [[ $STOP_XCAPE == y ]] ; then
    debug "tracking focus and managing xcape..."
  else
    debug "tracking focus..."
  fi

  # run program
  $OPTIRUN "$CMD" "${ARGS[@]}" &
  optirun_pid=$!
  debug "optirun PID: $optirun_pid"

  # if PROC_NAME was configured (only used if we started a launcher instead of the actual game)
  if [[ -n ${PROC_NAME:+x} ]] ; then
    count=0
    while [[ count -lt 10 ]]; do
      # wait for the executable to start
      sleep 2
      #echo "pgrep output: $(pgrep -fa "$PROC_NAME")"
      #echo "filtered output: $(pgrep -fa "$PROC_NAME" | grep -vE "$script_pid|$0")"
      if game_pid=$(pgrep "$PROC_NAME"); then
        if [[ -n $game_pid ]]; then
          debug "Game PID: $game_pid"
          break
        fi
      fi
      (( count++ ))
    done

    if [[ -z $game_pid ]] ; then
      error "Game PID was not found with \"pgrep -f $PROC_NAME\""
      error "Script exiting, since it won't know when to stop managing xcape (and taking up CPU cycles)"
      notify --error "Failed to find game PID, quitting"
      exit 1
    fi
  else
    game_pid=$optirun_pid
  fi

  if [[ -n ${WINDOW_CLASS:+x} ]]; then
    game_window=$(xdotool search --onlyvisible --sync --limit 1 --classname "^$WINDOW_CLASS\$")
  else
    game_window=$(xdotool search --onlyvisible --sync --limit 1 --name "$WINDOW_TITLE")
  fi

  focused_window=$(xdotool getwindowfocus)
  if [[ $focused_window -eq $game_window ]]; then
    log_time FOCUSED
    was_focused=y
  else
    log_time UNFOCUSED
    was_focused=n
  fi

  while kill -0 "$game_pid" 2>/dev/null; do
    focused_window=$(xdotool getwindowfocus)
    if [[ $focused_window -eq $game_window ]]; then
      if [[ $was_focused == n ]]; then
        debug "window focused"
        log_time FOCUSED
        try_pause_xcape
        was_focused=y
      fi
    else
      if [[ $was_focused == y ]]; then
        debug "window unfocused"
        log_time UNFOCUSED
        try_resume_xcape
        was_focused=n
      fi
    fi
    sleep 1
  done
else
  if [[ $STOP_XCAPE == y ]] ; then
    error "WINDOW_TITLE or WINDOW_CLASS were not specified, so we can't reenable xcape when the window is unfocused."
    notify --warn "Window name or class name were not specified; running without active focus tracking"
  fi
  log "Running without active focus tracking."
  try_pause_xcape
  $OPTIRUN "$CMD" "${ARGS[@]}" || true
fi

debug "game has stopped, exiting wrapper"
exit 0
