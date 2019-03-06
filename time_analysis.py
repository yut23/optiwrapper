#!/usr/bin/env python3
"""
Analyzes playtime logs.
"""
# pylint: disable=invalid-name, missing-docstring, too-few-public-methods

import datetime
from enum import Enum
import functools
import sys

from typing import List, NamedTuple

from wrapper import WRAPPER_DIR


EventType = Enum('EventType', 'START STOP LEAVE RETURN')
START = EventType.START
STOP = EventType.STOP
LEAVE = EventType.LEAVE
RETURN = EventType.RETURN


class Event(NamedTuple):
    event: EventType
    time: datetime.datetime

    def __eq__(self, other):
        if isinstance(other, Event):
            return self.event == other.event and self.time == other.time
        if isinstance(other, EventType):
            return self.event == other
        return NotImplemented


class Segment(NamedTuple):
    start: datetime.datetime
    duration: datetime.timedelta


EVENT_PAIRS = {
    (START, START): None,
    (START, STOP): 'keep',
    (START, LEAVE): 'keep',
    (START, RETURN): 'discard',
    (STOP, START): 'discard',
    (STOP, STOP): None,
    (STOP, LEAVE): None,
    (STOP, RETURN): None,
    (LEAVE, START): None,
    (LEAVE, STOP): 'discard',
    (LEAVE, LEAVE): None,
    (LEAVE, RETURN): 'discard',
    (RETURN, START): None,
    (RETURN, STOP): 'keep',
    (RETURN, LEAVE): 'keep',
    (RETURN, RETURN): None
}


def parse(entry: str) -> Event:
    ACTIONS = {
        'game started': EventType.START,
        'game stopped': EventType.STOP,
        'user left': EventType.LEAVE,
        'user returned': EventType.RETURN
    }
    dt, action = entry.split(': ')
    action = action.strip()
    if action not in ACTIONS:
        raise ValueError('Invalid action: "{}"'.format(action))

    return Event(ACTIONS[action], datetime.datetime.fromisoformat(dt))


def process(events: List[Event], print_invalid: bool = True) -> List[Segment]:
    """
    Reads a list of events, and produces all the time segments when the user
    was playing the game.
    """
    if len(events) < 2:
        raise ValueError('Not enough data points!')

    segments = list()
    for (line_num, curr_evt), next_evt in zip(enumerate(events, 1), events[1:]):
        action = EVENT_PAIRS[(curr_evt.event, next_evt.event)]
        if action is None:
            if print_invalid:
                print('Invalid event combination: {:s}, {:s} (line {})'
                      .format(curr_evt.event, next_evt.event, line_num))
        elif action == 'keep':
            segments.append(Segment(curr_evt.time, next_evt.time - curr_evt.time))
        elif action == 'discard':
            pass
        else:
            assert False, 'combination missing: {:s}, {:s} (line {})'.format(
                curr_evt.event, next_evt.event, line_num)
    return segments


USAGE = 'Usage: {} [-q] <path to log file or game name>'


if __name__ == '__main__':
    verbose = True
    if '-q' in sys.argv:
        sys.argv.remove('-q')
        verbose = False

    if len(sys.argv) < 2:
        print(USAGE.format(sys.argv[0]))
        sys.exit(1)
    if '-h' in sys.argv or '--help' in sys.argv:
        print(USAGE.format(sys.argv[0]))
        sys.exit(0)

    if sys.argv[1] == '-':
        lines = sys.stdin.readlines()
    else:
        try:
            with open(sys.argv[1], 'r') as f:
                lines = f.readlines()
        except OSError:
            with open(WRAPPER_DIR / 'time' / (sys.argv[1] + '.log'), 'r') as f:
                lines = f.readlines()

    evts = [parse(line) for line in lines]

    running_segs = process([e for e in evts if e.event in (START, STOP)], verbose)
    all_segs = process(evts, verbose)

    run_time = functools.reduce(lambda x, y: x + y, (s.duration for s in running_segs))
    active_time = functools.reduce(lambda x, y: x + y, (s.duration for s in all_segs))
    print('Total run time:    {}'.format(run_time))
    if any(e.event in (LEAVE, RETURN) for e in evts):
        print('Total active time: {}'.format(active_time))
