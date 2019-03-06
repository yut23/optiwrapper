#!/bin/bash

bash_out=$(mktemp)
python_out=$(mktemp)
trap '{ rm "$bash_out" "$python_out"; }' INT TERM EXIT

bash wrapper.sh -t "$@" 2>/dev/null > "$bash_out"
bash_code=$?
python wrapper.py -t "$@" 2>/dev/null > "$python_out"
python_code=$?

if [[ $bash_code -ne $python_code ]]; then
  echo "Return codes don't match:" "$@"
elif ! diff -q "$bash_out" "$python_out" >/dev/null; then
  echo 'Output differs:' "$@"
fi
