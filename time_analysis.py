#!/usr/bin/env python3
"""
Analyzes playtime logs.
"""

import datetime
import enum
import functools
import operator
import sys
from typing import List, NamedTuple, Optional

from optiwrapper.lib import WRAPPER_DIR


class EventType(enum.Enum):
    START = enum.auto()
    LEAVE = enum.auto()
    RETURN = enum.auto()
    STOP = enum.auto()


START = EventType.START
LEAVE = EventType.LEAVE
RETURN = EventType.RETURN
STOP = EventType.STOP


@functools.total_ordering
class Event(NamedTuple):
    event: Optional[EventType]
    time: datetime.datetime
    line_num: int

    def __eq__(self, other):
        if isinstance(other, Event):
            return self.event == other.event and self.time == other.time
        if isinstance(other, EventType):
            return self.event == other
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, Event):
            return self.time < other.time
        return NotImplemented


class Segment(NamedTuple):
    start: datetime.datetime
    duration: datetime.timedelta


# Notes:
# (LEAVE, LEAVE): short, can probably be discarded
# (LEAVE, START) should have a STOP inserted with the same timestamp as LEAVE
EVENT_PAIRS = {
    (START, START): None,
    (START, STOP): "keep",
    (START, LEAVE): "keep",
    (START, RETURN): "discard",
    (STOP, START): "discard",
    (STOP, STOP): None,
    (STOP, LEAVE): None,
    (STOP, RETURN): None,
    (LEAVE, START): None,
    (LEAVE, STOP): "discard",
    (LEAVE, LEAVE): None,
    (LEAVE, RETURN): "discard",
    (RETURN, START): None,
    (RETURN, STOP): "keep",
    (RETURN, LEAVE): "keep",
    (RETURN, RETURN): None,
}


def parse(entry: str, line_num: int) -> Event:
    ACTIONS = {
        "game started": EventType.START,
        "game stopped": EventType.STOP,
        "wrapper died": EventType.STOP,
        "user left": EventType.LEAVE,
        "user returned": EventType.RETURN,
    }
    dt, action = entry.split(": ")
    action = action.strip()
    if action not in ACTIONS:
        raise ValueError('Invalid action: "{}"'.format(action))

    event_type: Optional[EventType] = ACTIONS[action]
    if dt.startswith("#"):
        event_type = None
        dt = dt[1:]
    return Event(event_type, datetime.datetime.fromisoformat(dt), line_num)


def process(events: List[Event], print_invalid: bool = True) -> List[Segment]:
    """
    Reads a list of events, and produces all the time segments when the user
    was playing the game.
    """
    if len(events) < 2:
        raise ValueError("Not enough data points!")

    segments = []
    curr_evt = events[0]
    for line_num, next_evt in enumerate(events[1:], 2):
        if next_evt.event is None:
            continue
        if curr_evt.event is None:
            curr_evt = next_evt
            continue
        action = EVENT_PAIRS[(curr_evt.event, next_evt.event)]
        if action is None:
            if print_invalid:
                print(
                    "Invalid event combination: {:>6s}, {:6s} at lines {:5d}/+{:<3s} duration {:11.3f}s".format(
                        curr_evt.event.name,
                        next_evt.event.name,
                        curr_evt.line_num,
                        str(next_evt.line_num - curr_evt.line_num) + ",",
                        (next_evt.time - curr_evt.time).total_seconds(),
                    )
                )
        elif action == "keep":
            segments.append(Segment(curr_evt.time, next_evt.time - curr_evt.time))
        elif action == "discard":
            pass
        else:
            assert False, "combination missing: {:s}, {:s} (line {})".format(
                curr_evt.event, next_evt.event, line_num
            )
        curr_evt = next_evt
    return segments


USAGE = "Usage: {} [-q] <path to log file or game name>"


if __name__ == "__main__":
    verbose = True
    if "-q" in sys.argv:
        sys.argv.remove("-q")
        verbose = False

    if len(sys.argv) < 2:
        print(USAGE.format(sys.argv[0]))
        sys.exit(1)
    if "-h" in sys.argv or "--help" in sys.argv:
        print(USAGE.format(sys.argv[0]))
        sys.exit(0)

    if sys.argv[1] == "-":
        lines = sys.stdin.readlines()
    else:
        try:
            with open(sys.argv[1], "r") as f:
                lines = f.readlines()
        except OSError:
            with open(WRAPPER_DIR / "time" / (sys.argv[1] + ".log"), "r") as f:
                lines = f.readlines()

    evts = sorted(parse(line, i) for i, line in enumerate(lines, 1))

    running_segs = process([e for e in evts if e.event in (START, STOP)], verbose)
    all_segs = process(evts, verbose)

    run_time = functools.reduce(operator.add, (s.duration for s in running_segs))
    run_hours = run_time.total_seconds() / 60 / 60
    active_time = functools.reduce(operator.add, (s.duration for s in all_segs))
    active_hours = active_time.total_seconds() / 60 / 60
    print("Total run time:    {} ({:.2f} hours)".format(run_time, run_hours))
    if any(e.event in (LEAVE, RETURN) for e in evts):
        msg = "active"
    else:
        msg = "run"
    print("Total {} time: {} ({:.2f} hours)".format(msg, active_time, active_hours))
