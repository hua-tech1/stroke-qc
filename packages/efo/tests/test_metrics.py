# -*- coding: utf-8 -*-
from efo import Event, event_deltas, match_events


def _ev(code, frame):
    return Event(code=code, frame=frame, ts_ms=frame * 66.67, confidence=0.9, rule="r")


def test_perfect_match():
    ref = [_ev("device_visible_start", 12), _ev("device_visible_end", 44)]
    test = [_ev("device_visible_start", 13), _ev("device_visible_end", 45)]
    m = match_events(ref, test, tol_frames=2)
    assert m.tp == 2 and m.fp == 0 and m.fn == 0
    assert m.f1 == 1.0


def test_miss_recall():
    ref = [_ev("device_visible_start", 12), _ev("device_visible_end", 44)]
    test = [_ev("device_visible_start", 12)]
    m = match_events(ref, test, tol_frames=2)
    assert m.fn == 1
    assert abs(m.recall - 0.5) < 1e-9


def test_event_deltas_frames():
    ref = [_ev("device_visible_start", 12)]
    test = [_ev("device_visible_start", 14)]
    assert event_deltas(ref, test, tol_frames=2) == [2]
