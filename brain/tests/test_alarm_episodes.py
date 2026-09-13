import pytest

from brain.alarm_episodes import AlarmEpisodeTracker


def test_repeated_alarm_observations_form_one_episode():
    tracker = AlarmEpisodeTracker(clear_hold_ms=10_000)
    tracker.observe(1_000, True)
    tracker.observe(2_000, True)
    tracker.observe(3_000, False)
    tracker.observe(13_000, False)

    episodes = tracker.finalize(20_000)
    assert len(episodes) == 1
    assert episodes[0].start_ms == 1_000
    assert episodes[0].end_ms == 13_000


def test_clear_interruption_keeps_episode_open():
    tracker = AlarmEpisodeTracker(clear_hold_ms=10_000)
    tracker.observe(1_000, True)
    tracker.observe(3_000, False)
    tracker.observe(8_000, True)
    tracker.observe(12_000, False)

    episodes = tracker.finalize(15_000)
    assert len(episodes) == 1
    assert episodes[0].end_ms == 15_000


def test_out_of_order_observations_are_rejected():
    tracker = AlarmEpisodeTracker()
    tracker.observe(2_000, True)
    with pytest.raises(ValueError, match="chronological"):
        tracker.observe(1_000, False)
