"""
Prototype 1: Event-Time Watermark Windowing Engine
===================================================
Implements tumbling and sliding window aggregation from scratch with:
  - Event-time vs processing-time distinction
  - Watermark-based window closing (handles out-of-order events)
  - Late event side output (events arriving after watermark are captured, not silently dropped)
  - Per-key state management

No dependencies beyond the Python standard library.

Run:  python windowing_engine.py
"""

from __future__ import annotations
import heapq
import time
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Generator, Iterator


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(order=True)
class Event:
    """A single stream event."""
    event_time: float          # When the event actually occurred (seconds since epoch)
    key: str = field(compare=False)
    value: float = field(compare=False)
    processing_time: float = field(default_factory=time.time, compare=False)

    def __repr__(self) -> str:
        return f"Event(key={self.key!r}, value={self.value}, et={self.event_time:.1f})"


@dataclass
class Window:
    """A half-open time interval [start, end)."""
    start: float
    end: float

    def contains(self, event_time: float) -> bool:
        return self.start <= event_time < self.end

    def __repr__(self) -> str:
        return f"Window[{self.start:.0f}, {self.end:.0f})"


@dataclass
class WindowResult:
    """Emitted when a window is closed."""
    window: Window
    key: str
    count: int
    total: float
    mean: float
    min_val: float
    max_val: float
    late: bool = False      # True if this came from the late-event side output

    def __repr__(self) -> str:
        tag = " [LATE]" if self.late else ""
        return (
            f"Result{tag} {self.window} key={self.key!r} "
            f"count={self.count} mean={self.mean:.2f} "
            f"min={self.min_val:.2f} max={self.max_val:.2f}"
        )


# ---------------------------------------------------------------------------
# Window assignment
# ---------------------------------------------------------------------------

def tumbling_windows(event_time: float, size: float) -> list[Window]:
    """Assign an event to exactly one tumbling window."""
    start = (event_time // size) * size
    return [Window(start, start + size)]


def sliding_windows(event_time: float, size: float, slide: float) -> list[Window]:
    """
    Assign an event to all overlapping sliding windows it falls into.
    Number of windows = ceil(size / slide).
    """
    last_start = (event_time // slide) * slide
    windows = []
    w_start = last_start
    while w_start > event_time - size:
        if w_start <= event_time < w_start + size:
            windows.append(Window(w_start, w_start + size))
        w_start -= slide
    return windows


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class WatermarkWindowEngine:
    """
    Event-time windowing engine with watermark-based window closing.

    Parameters
    ----------
    window_fn   : Callable that maps (event_time, **kwargs) → list[Window]
    window_kwargs : Extra args passed to window_fn (e.g. size=, slide=)
    allowed_lateness : Events arriving this many seconds after the watermark
                       are routed to the late side output instead of dropped.
    watermark_lag : How far behind the max seen event_time the watermark trails
                    (accounts for natural out-of-order delay in the source).
    """

    def __init__(
        self,
        window_fn: Callable,
        window_kwargs: dict,
        allowed_lateness: float = 0.0,
        watermark_lag: float = 5.0,
    ):
        self.window_fn = window_fn
        self.window_kwargs = window_kwargs
        self.allowed_lateness = allowed_lateness
        self.watermark_lag = watermark_lag

        # watermark: no event with event_time < watermark will arrive
        self._watermark: float = float("-inf")
        self._max_event_time: float = float("-inf")

        # pending[window_key][event_key] → list of values
        # window_key = (start, end)
        self._pending: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

        # side output for late events
        self._late_buffer: list[Event] = []

        # emitted results (in order of window closing)
        self.results: list[WindowResult] = []
        self.late_results: list[WindowResult] = []

        # stats
        self.events_processed = 0
        self.events_late = 0
        self.windows_closed = 0

    @property
    def watermark(self) -> float:
        return self._watermark

    def process(self, event: Event) -> list[WindowResult]:
        """
        Ingest one event. Returns any WindowResults that became ready
        (i.e., their window end ≤ new watermark).
        """
        self.events_processed += 1

        # Advance watermark
        if event.event_time > self._max_event_time:
            self._max_event_time = event.event_time
            new_watermark = self._max_event_time - self.watermark_lag
            closed = self._advance_watermark(new_watermark)
        else:
            closed = []

        # Route: is this event late?
        deadline = self._watermark - self.allowed_lateness
        if event.event_time < deadline:
            # Truly late — emit a late result immediately
            self.events_late += 1
            late_results = self._emit_late(event)
            self.late_results.extend(late_results)
            return closed + late_results

        # Assign to windows and buffer
        windows = self.window_fn(event.event_time, **self.window_kwargs)
        for w in windows:
            self._pending[(w.start, w.end)][event.key].append(event.value)

        return closed

    def _advance_watermark(self, new_watermark: float) -> list[WindowResult]:
        """Close all windows whose end ≤ new watermark."""
        if new_watermark <= self._watermark:
            return []
        self._watermark = new_watermark

        closed = []
        to_remove = []
        for (w_start, w_end), key_data in self._pending.items():
            if w_end <= self._watermark:
                w = Window(w_start, w_end)
                for key, values in key_data.items():
                    result = WindowResult(
                        window=w,
                        key=key,
                        count=len(values),
                        total=sum(values),
                        mean=sum(values) / len(values),
                        min_val=min(values),
                        max_val=max(values),
                    )
                    closed.append(result)
                    self.results.append(result)
                    self.windows_closed += 1
                to_remove.append((w_start, w_end))

        for k in to_remove:
            del self._pending[k]

        closed.sort(key=lambda r: r.window.start)
        return closed

    def _emit_late(self, event: Event) -> list[WindowResult]:
        """Emit a single-event result for a truly late event."""
        windows = self.window_fn(event.event_time, **self.window_kwargs)
        results = []
        for w in windows:
            results.append(WindowResult(
                window=w,
                key=event.key,
                count=1,
                total=event.value,
                mean=event.value,
                min_val=event.value,
                max_val=event.value,
                late=True,
            ))
        return results

    def flush(self) -> list[WindowResult]:
        """Force-close all remaining open windows (end-of-stream)."""
        return self._advance_watermark(float("inf"))

    def stats(self) -> dict:
        return {
            "events_processed": self.events_processed,
            "events_late": self.events_late,
            "windows_closed": self.windows_closed,
            "watermark": round(self._watermark, 2),
        }


# ---------------------------------------------------------------------------
# Event generators
# ---------------------------------------------------------------------------

def in_order_stream(
    n: int = 100,
    keys: list[str] = None,
    start_time: float = 1000.0,
    interval: float = 1.0,
) -> Iterator[Event]:
    keys = keys or ["sensor-A", "sensor-B"]
    for i in range(n):
        yield Event(
            event_time=start_time + i * interval,
            key=random.choice(keys),
            value=random.gauss(100, 15),
        )


def out_of_order_stream(
    n: int = 100,
    keys: list[str] = None,
    start_time: float = 1000.0,
    max_delay: float = 8.0,
    late_pct: float = 0.05,
) -> Iterator[Event]:
    """
    Simulates a realistic stream:
    - Events are mostly in order but randomly delayed by up to max_delay seconds.
    - A small fraction (late_pct) are very late (beyond the watermark lag).
    """
    keys = keys or ["sensor-A", "sensor-B", "sensor-C"]
    base_events = list(in_order_stream(n, keys, start_time))

    # Shuffle based on random delay (simulates network jitter)
    delayed = []
    for i, e in enumerate(base_events):
        delay = random.uniform(0, max_delay)
        # Mark some events as very late
        if random.random() < late_pct:
            delay += 20.0
        delayed.append((e.event_time + delay, e))

    # Sort by arrival order (processing time ~ event_time + delay)
    delayed.sort(key=lambda x: x[0])
    for _, e in delayed:
        yield e


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo_tumbling():
    print("=" * 70)
    print("DEMO 1: Tumbling Windows (size=10s, watermark_lag=5s)")
    print("=" * 70)

    engine = WatermarkWindowEngine(
        window_fn=tumbling_windows,
        window_kwargs={"size": 10.0},
        watermark_lag=5.0,
        allowed_lateness=2.0,
    )

    events = list(out_of_order_stream(n=80, start_time=1000.0, max_delay=6.0, late_pct=0.05))
    print(f"Processing {len(events)} events (out-of-order, ~5% very late)...\n")

    for event in events:
        new_results = engine.process(event)
        for r in new_results:
            print(f"  CLOSED: {r}")

    # Flush remaining windows
    final = engine.flush()
    for r in final:
        print(f"  FLUSHED: {r}")

    print(f"\nStats: {engine.stats()}")
    if engine.late_results:
        print(f"\nLate events routed to side output ({len(engine.late_results)}):")
        for r in engine.late_results:
            print(f"  {r}")


def demo_sliding():
    print("\n" + "=" * 70)
    print("DEMO 2: Sliding Windows (size=20s, slide=5s, watermark_lag=3s)")
    print("=" * 70)

    engine = WatermarkWindowEngine(
        window_fn=sliding_windows,
        window_kwargs={"size": 20.0, "slide": 5.0},
        watermark_lag=3.0,
        allowed_lateness=1.0,
    )

    events = list(in_order_stream(n=40, start_time=0.0, interval=1.0))
    print(f"Processing {len(events)} in-order events...\n")

    for event in events:
        new_results = engine.process(event)
        for r in new_results:
            print(f"  CLOSED: {r}")

    final = engine.flush()
    for r in final:
        print(f"  FLUSHED: {r}")

    print(f"\nStats: {engine.stats()}")
    print(f"Each event falls into {20//5} overlapping windows "
          f"(size/slide = {20//5}x more results than tumbling)")


def demo_watermark_progression():
    print("\n" + "=" * 70)
    print("DEMO 3: Watermark Progression Visualization")
    print("=" * 70)
    print("Showing how watermark advances and triggers window closing.\n")

    engine = WatermarkWindowEngine(
        window_fn=tumbling_windows,
        window_kwargs={"size": 10.0},
        watermark_lag=5.0,
        allowed_lateness=3.0,
    )

    # Manually crafted event sequence to show watermark logic clearly
    manual_events = [
        Event(event_time=1001, key="A", value=1),
        Event(event_time=1003, key="B", value=2),
        Event(event_time=1007, key="A", value=3),  # watermark → 1002 (no window closed)
        Event(event_time=1012, key="B", value=4),  # watermark → 1007 (closes [1000,1010)? no, need 1010)
        Event(event_time=1016, key="A", value=5),  # watermark → 1011 → closes [1000,1010) ✓
        Event(event_time=1002, key="A", value=99), # LATE: et=1002 < watermark=1011, but within allowed_lateness=3? No → truly late
        Event(event_time=1009, key="C", value=7),  # late but within allowed_lateness? et=1009, deadline=1011-3=1008 → borderline
        Event(event_time=1025, key="A", value=8),  # watermark → 1020 → closes [1010,1020) ✓
    ]

    for e in manual_events:
        results = engine.process(e)
        wm_display = f"{engine.watermark:.0f}" if engine.watermark != float("-inf") else "-∞"
        print(f"  Ingest {e!r:50s}  watermark={wm_display}")
        for r in results:
            print(f"    → {r}")

    final = engine.flush()
    for r in final:
        print(f"  FLUSH → {r}")

    print(f"\nStats: {engine.stats()}")
    if engine.late_results:
        print(f"\nLate side output ({len(engine.late_results)} events):")
        for r in engine.late_results:
            print(f"  {r}")


if __name__ == "__main__":
    random.seed(42)
    demo_watermark_progression()
    demo_tumbling()
    demo_sliding()
