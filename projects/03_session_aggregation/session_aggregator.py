"""
Prototype 3: Session Window Aggregation
========================================
Session windows group events by a per-key inactivity gap rather than by a
fixed time boundary. A session ends when no event for that key arrives within
the gap_timeout. This is the hardest window type because:
  - Window boundaries are data-dependent (not clock-derived)
  - Sessions can merge when a late event falls between two existing sessions
  - State per key is a dynamic set of open sessions, not a fixed-size buffer

This prototype implements:
  - Gap-based session detection with per-key state
  - Session merging when a bridging event arrives
  - Session metrics: event count, dwell time, conversion rate, value sum
  - Pathway-style incremental processing (pure Python, no cluster needed)

Run:  python session_aggregator.py
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClickEvent:
    user_id: str
    page: str
    event_time: float       # seconds since epoch
    value: float = 0.0      # e.g. revenue if a purchase
    is_conversion: bool = False

    def __repr__(self) -> str:
        tag = " 💰" if self.is_conversion else ""
        return f"Click(user={self.user_id}, page={self.page!r}, t={self.event_time:.1f}{tag})"


@dataclass
class Session:
    """An open or closed session for a single user."""
    user_id: str
    session_id: int
    start_time: float
    end_time: float         # last seen event time (advances as events arrive)
    events: list[ClickEvent] = field(default_factory=list)
    closed: bool = False

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def total_value(self) -> float:
        return sum(e.value for e in self.events)

    @property
    def has_conversion(self) -> bool:
        return any(e.is_conversion for e in self.events)

    @property
    def pages_visited(self) -> list[str]:
        return [e.page for e in self.events]

    def overlaps_or_bridges(self, event_time: float, gap_timeout: float) -> bool:
        """True if event_time falls within this session's active range."""
        return self.start_time <= event_time <= self.end_time + gap_timeout

    def add(self, event: ClickEvent) -> None:
        self.events.append(event)
        if event.event_time > self.end_time:
            self.end_time = event.event_time
        if event.event_time < self.start_time:
            self.start_time = event.event_time

    def merge_with(self, other: "Session") -> None:
        """Absorb another session into this one (session merging)."""
        for e in other.events:
            self.add(e)

    def summary(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "start": round(self.start_time, 1),
            "end": round(self.end_time, 1),
            "duration_s": round(self.duration, 1),
            "events": self.event_count,
            "pages": self.pages_visited,
            "total_value": round(self.total_value, 2),
            "converted": self.has_conversion,
        }

    def __repr__(self) -> str:
        conv = " [CONVERTED]" if self.has_conversion else ""
        return (
            f"Session(user={self.user_id}, id={self.session_id}, "
            f"t=[{self.start_time:.0f}–{self.end_time:.0f}], "
            f"events={self.event_count}, value={self.total_value:.2f}{conv})"
        )


# ---------------------------------------------------------------------------
# Session engine
# ---------------------------------------------------------------------------

class SessionWindowEngine:
    """
    Stateful session window processor.

    Per-key state: a sorted list of open Session objects.
    On each event:
      1. Find all open sessions that would be bridged by this event.
      2. If none → open a new session.
      3. If one → extend it.
      4. If multiple → merge them all (the new event bridges two previously
         separate sessions).
      5. Close sessions whose end_time + gap_timeout < current watermark.

    Parameters
    ----------
    gap_timeout     : Inactivity gap in seconds that closes a session.
    watermark_lag   : How far behind the max seen event_time the watermark trails.
    min_events      : Sessions with fewer events than this are discarded (noise filter).
    """

    def __init__(
        self,
        gap_timeout: float = 30.0,
        watermark_lag: float = 10.0,
        min_events: int = 1,
    ):
        self.gap_timeout = gap_timeout
        self.watermark_lag = watermark_lag
        self.min_events = min_events

        # Per-user open sessions
        self._open: dict[str, list[Session]] = defaultdict(list)
        self._session_counter: dict[str, int] = defaultdict(int)

        # Completed sessions
        self.closed_sessions: list[Session] = []
        self._max_event_time: float = float("-inf")
        self._watermark: float = float("-inf")

        # Stats
        self.events_processed = 0
        self.merges = 0

    def process(self, event: ClickEvent) -> list[Session]:
        """Ingest one event. Returns any sessions that were just closed."""
        self.events_processed += 1

        # Advance watermark
        if event.event_time > self._max_event_time:
            self._max_event_time = event.event_time
            self._watermark = self._max_event_time - self.watermark_lag

        user = event.user_id
        open_sessions = self._open[user]

        # Find sessions bridged by this event
        bridged = [
            s for s in open_sessions
            if s.overlaps_or_bridges(event.event_time, self.gap_timeout)
        ]

        if not bridged:
            # Open a new session
            self._session_counter[user] += 1
            new_session = Session(
                user_id=user,
                session_id=self._session_counter[user],
                start_time=event.event_time,
                end_time=event.event_time,
            )
            new_session.add(event)
            self._open[user].append(new_session)
        elif len(bridged) == 1:
            # Extend existing session
            bridged[0].add(event)
        else:
            # Merge multiple bridged sessions into the earliest one
            self.merges += 1
            primary = min(bridged, key=lambda s: s.start_time)
            for other in bridged:
                if other is not primary:
                    primary.merge_with(other)
                    self._open[user].remove(other)
            primary.add(event)

        # Evict sessions whose inactivity window has passed the watermark
        return self._close_expired(user)

    def _close_expired(self, user: str) -> list[Session]:
        """Close sessions that expired before the current watermark."""
        expired = []
        remaining = []
        for s in self._open[user]:
            if s.end_time + self.gap_timeout < self._watermark:
                s.closed = True
                if s.event_count >= self.min_events:
                    self.closed_sessions.append(s)
                    expired.append(s)
            else:
                remaining.append(s)
        self._open[user] = remaining
        return expired

    def flush(self) -> list[Session]:
        """Force-close all remaining open sessions (end-of-stream)."""
        flushed = []
        for user, sessions in self._open.items():
            for s in sessions:
                s.closed = True
                if s.event_count >= self.min_events:
                    self.closed_sessions.append(s)
                    flushed.append(s)
        self._open.clear()
        return flushed

    def stats(self) -> dict:
        return {
            "events_processed": self.events_processed,
            "sessions_closed": len(self.closed_sessions),
            "sessions_open": sum(len(v) for v in self._open.values()),
            "session_merges": self.merges,
            "watermark": round(self._watermark, 1),
        }


# ---------------------------------------------------------------------------
# Event generator
# ---------------------------------------------------------------------------

PAGES = ["/home", "/products", "/product/1", "/product/2", "/cart", "/checkout", "/order-confirm"]
CONVERSION_PAGES = {"/order-confirm"}

def generate_clickstream(
    n_users: int = 20,
    n_events: int = 500,
    session_gap: float = 30.0,     # seconds between sessions
    events_per_session: tuple = (3, 15),
    session_gap_range: tuple = (60, 300),
) -> list[ClickEvent]:
    """Generate a realistic multi-user clickstream with natural sessions."""
    rng = random.Random(42)
    events = []

    for user_idx in range(n_users):
        user_id = f"user-{user_idx:03d}"
        t = rng.uniform(1000, 1100)  # stagger user start times
        n_sessions = rng.randint(1, 4)

        for _ in range(n_sessions):
            # Generate a burst of clicks within one session
            n_clicks = rng.randint(*events_per_session)
            for click_idx in range(n_clicks):
                page = rng.choice(PAGES)
                t += rng.uniform(2, 20)  # 2-20 sec between clicks within session
                is_conversion = page in CONVERSION_PAGES and click_idx == n_clicks - 1
                value = round(rng.uniform(20, 200), 2) if is_conversion else 0.0
                events.append(ClickEvent(
                    user_id=user_id,
                    page=page,
                    event_time=t,
                    value=value,
                    is_conversion=is_conversion,
                ))
            # Gap between sessions
            t += rng.uniform(*session_gap_range)

    # Sort by event_time (simulating a time-ordered stream)
    events.sort(key=lambda e: e.event_time)
    return events


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo():
    print("=" * 70)
    print("Session Window Aggregation Demo")
    print("=" * 70)

    engine = SessionWindowEngine(gap_timeout=30.0, watermark_lag=10.0, min_events=2)
    stream = generate_clickstream(n_users=10, n_events=500)

    print(f"\nProcessing {len(stream)} events from {len({e.user_id for e in stream})} users...")
    print("(Sessions auto-close when inactivity > 30s past watermark)\n")

    newly_closed_all = []
    for event in stream:
        newly_closed = engine.process(event)
        newly_closed_all.extend(newly_closed)

    # Flush remaining open sessions
    flushed = engine.flush()

    all_sessions = engine.closed_sessions

    print(f"Stats: {engine.stats()}\n")

    # --- Session summary ---
    print(f"{'User':<12} {'Sess':>5} {'Start':>8} {'End':>8} {'Dur':>6} "
          f"{'Events':>7} {'Value':>8} {'Conv':>6}")
    print("-" * 65)
    for s in sorted(all_sessions, key=lambda s: s.start_time)[:25]:
        print(f"{s.user_id:<12} {s.session_id:>5} {s.start_time:>8.0f} "
              f"{s.end_time:>8.0f} {s.duration:>5.0f}s {s.event_count:>7} "
              f"${s.total_value:>7.2f} {'✓' if s.has_conversion else '':>6}")

    # --- Aggregate metrics ---
    print(f"\n--- Aggregate metrics across all {len(all_sessions)} sessions ---")
    converted = [s for s in all_sessions if s.has_conversion]
    avg_duration = sum(s.duration for s in all_sessions) / len(all_sessions)
    avg_events   = sum(s.event_count for s in all_sessions) / len(all_sessions)
    total_revenue = sum(s.total_value for s in all_sessions)
    conversion_rate = len(converted) / len(all_sessions) * 100

    print(f"  Total sessions     : {len(all_sessions)}")
    print(f"  Avg session duration: {avg_duration:.1f}s")
    print(f"  Avg events/session  : {avg_events:.1f}")
    print(f"  Total revenue       : ${total_revenue:.2f}")
    print(f"  Conversion rate     : {conversion_rate:.1f}%  ({len(converted)} sessions)")
    print(f"  Session merges      : {engine.merges}")

    # --- Session merge demo ---
    print("\n--- Session merge demo ---")
    print("Showing what happens when a bridging event arrives between two existing sessions.")
    merge_engine = SessionWindowEngine(gap_timeout=20.0, watermark_lag=0.0)

    # Session 1: t=100..140 (gap ends at t=160)
    # Session 2: t=170..200 (gap ends at t=220)
    # Bridging event at t=155 → should merge sessions 1 and 2
    demo_events = [
        ClickEvent("alice", "/home",     event_time=100),
        ClickEvent("alice", "/products", event_time=120),
        ClickEvent("alice", "/cart",     event_time=140),
        # Gap
        ClickEvent("alice", "/home",     event_time=170),
        ClickEvent("alice", "/checkout", event_time=190, is_conversion=True, value=99.99),
        # Bridging event that merges both (arrives late, falls between the two sessions)
        ClickEvent("alice", "/product/1",event_time=155),
    ]

    for e in demo_events:
        closed = merge_engine.process(e)
        for s in closed:
            print(f"  Closed: {s}")

    flushed_demo = merge_engine.flush()
    for s in flushed_demo:
        print(f"  Flushed: {s}")
        print(f"  Pages visited: {s.pages_visited}")
        print(f"  Merges that occurred: {merge_engine.merges}")


if __name__ == "__main__":
    run_demo()
