import pytest

from v500capture.scheduler import Scheduler, Tick

START = 1_000_000.0
MIN = 60.0


def test_first_scan_fires_immediately():
    s = Scheduler(START, 20 * MIN)
    tick = s.poll(START, busy=False)
    assert tick.fire == 0 and tick.skipped == [] and not tick.finished


def test_fires_once_per_slot():
    s = Scheduler(START, 20 * MIN)
    assert s.poll(START, False).fire == 0
    assert s.poll(START + 1, False).fire is None
    assert s.poll(START + 20 * MIN - 1, False).fire is None
    assert s.poll(START + 20 * MIN, False).fire == 1
    assert s.next_time() == START + 40 * MIN


def test_busy_slot_is_skipped_not_run_late():
    s = Scheduler(START, 20 * MIN)
    s.poll(START, False)
    tick = s.poll(START + 20 * MIN + 5, busy=True)
    assert tick.fire is None and tick.skipped == [1]
    assert s.poll(START + 25 * MIN, False).fire is None  # not run late
    assert s.poll(START + 40 * MIN, False).fire == 2


def test_missed_slots_after_sleep_run_latest_only():
    s = Scheduler(START, 20 * MIN)
    s.poll(START, False)
    tick = s.poll(START + 70 * MIN, False)  # slots 1, 2, 3 are all due
    assert tick.fire == 3 and tick.skipped == [1, 2]


def test_end_time_stops_new_scans():
    s = Scheduler(START, 20 * MIN, end=START + 50 * MIN)
    assert s.poll(START, False).fire == 0
    assert s.poll(START + 20 * MIN, False).fire == 1
    assert s.poll(START + 40 * MIN, False).fire == 2
    assert s.next_time() is None  # slot 3 (60 min) is after the end
    assert s.poll(START + 50 * MIN, False).finished


def test_slot_due_just_before_end_still_runs():
    s = Scheduler(START, 20 * MIN, end=START + 40 * MIN + 0.5)
    s.poll(START, False)
    s.poll(START + 20 * MIN, False)
    assert s.poll(START + 40 * MIN - 0.01, False).fire is None
    tick = s.poll(START + 40 * MIN + 0.99, False)  # first poll to see slot 2 is past the end
    assert tick.fire == 2 and tick.finished
    assert s.poll(START + 40 * MIN + 2, False) == Tick(finished=True)


def test_slots_before_end_logged_as_missed_after_sleep():
    s = Scheduler(START, 20 * MIN, end=START + 50 * MIN)
    s.poll(START, False)
    tick = s.poll(START + 180 * MIN, False)  # asleep through the end time
    assert tick.fire is None and tick.skipped == [1, 2] and tick.finished


def test_remaining_slots():
    s = Scheduler(START, 20 * MIN, end=START + 60 * MIN)
    assert s.remaining_slots() == 3  # 0, 20, 40 min
    s.poll(START, False)
    assert s.remaining_slots() == 2
    assert Scheduler(START, 20 * MIN).remaining_slots() is None


def test_invalid_arguments():
    with pytest.raises(ValueError):
        Scheduler(START, 0)
    with pytest.raises(ValueError):
        Scheduler(START, MIN, end=START)
