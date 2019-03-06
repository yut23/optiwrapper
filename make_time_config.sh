#!/bin/bash -eu
set -o pipefail

source /home/eric/bin/lib/lib.sh

check_usage "Usage: $0 <appid> <game name>" 2 2 "$@"

appid=$1
name=$2

pushd ~/Games/wrapper/config > /dev/null || exit 1

outfile="$name.cfg"
if [[ -e "$outfile" ]]; then
  echo "Config file for \"$name\" already exists. Exiting."
  exit 1
fi

xdg-open "steam://rungameid/$appid"
winid=$(xdotool selectwindow)
classname=$(xprop -id "$winid" 8s '\t$0' WM_CLASS | cut -f2 | sed 's/^"\(.*\)"$/\1/')

if [[ $classname =~ WM_CLASS.*not\ found ]]; then
  winname=$(xprop -id "$winid" 8s '\t$0' WM_NAME | cut -f2 | sed 's/^"\(.*\)"$/\1/')
  echo "Using window name: \"$winname\""
  sed -e "
/^#WINDOW_NAME=.*\$/ c\
WINDOW_NAME='^$winname\$'
" time-tracking.cfg > "$outfile"
else
  echo "Using class name: \"$classname\""
  sed -e "
/^#WINDOW_CLASSNAME=.*\$/ c\
WINDOW_CLASSNAME='$classname'
" time-tracking.cfg > "$outfile"
fi
