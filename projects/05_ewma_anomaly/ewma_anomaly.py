"""
Prototype 5: EWMA Anomaly Detection + Sliding Window Join
==========================================================
Combines two advanced stateful patterns:

1. **Time-continuous EWMA (Exponential Weighted Moving Average)**
   Rather than fixed windows that treat all events equally, EWMA naturally
   weights recent events more heavily. Using continuous-time decay:
       EMA(t) = value(t) + EMA(t_prev) × exp(-α × Δt)
   This handles irregular timestamps correctly — a 5-minute gap decays more
   than a 1-second gap, unlike discrete EWMAs.

2. **Sliding Window Join (two streams)**
   Joins a stream of sensor readings against a stream of per-sensor
   threshold updates. For each reading, the relevant threshold is the most
   recent one published within the join window [reading_time - W, reading_time].
   This is a common pattern: "apply the latest configuration/policy to each event."

3. **Anomaly scoring**
   A reading is anomalous if it deviates from the EWMA by more than N standard
   deviations (Bollinger Band-style). The EWMA variance is also maintained
   incrementally using a parallel exponential moving variance.

No dependencies beyond the Python standard library.

Run:  python ewma_anomaly.py
"""

from __future__ import annotations
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SensorReading:
    sensor_id: str
    value: float
    event_time: float       # seconds since epoch

    def __repr__(self) -> str:
        return f"Reading(sensor={self.sensor_id}, val={self.value:.2f}, t={self.event_time:.1f})"


@dataclass
class ThresholdUpdate:
    sensor_id: str
    threshold: float        # absolute threshold (readings above this are anomalous)
    event_time: float

    def __repr__(self) -> str:
        return f"Threshold(sensor={self.sensor_id}, thresh={self.threshold:.2f}, t={self.event_time:.1f})"


@dataclass
class AnomalyAlert:
    sensor_id: str
    value: float
    event_time: float
    ewma: float
    ewma_std: float
    z_score: float          # how many std deviations from EWMA
    threshold: Optional[float]
    triggered_by: str       # "z_score", "threshold", or "both"

    def __repr__(self) -> str:
        return (
            f"🚨 ANOMALY sensor={self.sensor_id} val={self.value:.2f} "
            f"ewma={self.ewma:.2f}±{self.ewma_std:.2f} z={self.z_score:+.2f} "
            f"[{self.triggered_by}] t={self.event_time:.1f}"
        )


# ---------------------------------------------------------------------------
# Time-continuous EWMA state (per sensor)
# ---------------------------------------------------------------------------

class EWMAState:
    """
    Maintains an exponentially weighted moving average and variance
    for a single time series with irregular timestamps.

    The time-continuous formulation:
        EMA(t)  = v(t) + EMA(t_prev) × λ
        EMVAR(t) = (1-λ) × (v(t) - EMA(t_prev))² + λ × EMVAR(t_prev)
    where:
        λ = exp(-α × Δt)       (decay factor for this time step)
        α = ln(2) / half_life  (decay rate in seconds⁻¹)

    Parameters
    ----------
    half_life : Number of seconds after which an event's weight halves.
                Small half_life → fast response, more noise.
                Large half_life → slow response, more stable.
    warmup_events : Number of events before the state is considered stable.
    z_threshold : Standard deviations above/below EWMA to flag anomalies.
    """

    def __init__(
        self,
        half_life: float = 60.0,
        warmup_events: int = 5,
        z_threshold: float = 3.0,
    ):
        self.half_life = half_life
        self.alpha = math.log(2) / half_life  # decay rate
        self.z_threshold = z_threshold
        self.warmup_events = warmup_events

        self._ema: Optional[float] = None
        self._emvar: float = 0.0
        self._last_time: Optional[float] = None
        self._n: int = 0

    @property
    def is_warmed_up(self) -> bool:
        return self._n >= self.warmup_events

    @property
    def ema(self) -> Optional[float]:
        return self._ema

    @property
    def std(self) -> float:
        return math.sqrt(max(0.0, self._emvar))

    def update(self, value: float, event_time: float) -> Optional[float]:
        """
        Ingest a new value. Returns the z-score if warmed up, else None.
        """
        self._n += 1

        if self._ema is None:
            self._ema = value
            self._last_time = event_time
            return None

        # Time-continuous decay factor
        dt = max(0.0, event_time - self._last_time)
        lam = math.exp(-self.alpha * dt)

        # Update EWMA: weighted blend — λ weight on old, (1-λ) on new value
        prev_ema = self._ema
        self._ema = (1 - lam) * value + lam * prev_ema

        # Update exponential moving variance (Welford-style for EMA)
        diff = value - prev_ema
        self._emvar = (1 - lam) * diff * diff + lam * self._emvar

        self._last_time = event_time

        if not self.is_warmed_up:
            return None

        std = self.std
        if std < 1e-9:
            return 0.0

        return (value - self._ema) / std

    def z_score(self, value: float) -> float:
        """Compute z-score without updating state."""
        if self._ema is None or self.std < 1e-9:
            return 0.0
        return (value - self._ema) / self.std


# ---------------------------------------------------------------------------
# Sliding window join (sensor readings × threshold updates)
# ---------------------------------------------------------------------------

class SlidingWindowJoin:
    """
    Joins SensorReadings against ThresholdUpdates over a sliding window.

    For each SensorReading at time t, finds the most recent ThresholdUpdate
    for the same sensor_id within [t - window_size, t].

    State: a deque of recent ThresholdUpdates per sensor (evicted when they
    fall outside the window relative to the current watermark).

    This models the general pattern: "apply the current configuration to each event."
    """

    def __init__(self, window_size: float = 300.0, watermark_lag: float = 10.0):
        self.window_size = window_size
        self.watermark_lag = watermark_lag
        # sensor_id → deque of (event_time, threshold), sorted ascending
        self._threshold_buffer: dict[str, deque] = {}
        self._max_time: float = float("-inf")
        self._watermark: float = float("-inf")

    def ingest_threshold(self, update: ThresholdUpdate) -> None:
        """Add a threshold update to the buffer."""
        sid = update.sensor_id
        if sid not in self._threshold_buffer:
            self._threshold_buffer[sid] = deque()
        self._threshold_buffer[sid].append((update.event_time, update.threshold))
        self._advance_watermark(update.event_time)

    def lookup_threshold(self, reading: SensorReading) -> Optional[float]:
        """
        Find the most recent threshold for this sensor within
        [reading.event_time - window_size, reading.event_time].
        Returns None if no threshold update exists in the window.
        """
        self._advance_watermark(reading.event_time)
        buf = self._threshold_buffer.get(reading.sensor_id)
        if not buf:
            return None

        cutoff = reading.event_time - self.window_size
        result = None
        for (t, thresh) in buf:
            if cutoff <= t <= reading.event_time:
                result = thresh  # take the latest (buf is sorted ascending)

        return result

    def _advance_watermark(self, event_time: float) -> None:
        if event_time > self._max_time:
            self._max_time = event_time
            self._watermark = self._max_time - self.watermark_lag
        self._evict_expired()

    def _evict_expired(self) -> None:
        """Remove threshold updates too old to be useful."""
        eviction_cutoff = self._watermark - self.window_size
        for buf in self._threshold_buffer.values():
            while buf and buf[0][0] < eviction_cutoff:
                buf.popleft()


# ---------------------------------------------------------------------------
# Anomaly detector (combines EWMA + sliding window join)
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Processes a merged stream of SensorReadings and ThresholdUpdates.

    For each reading:
      1. Update the per-sensor EWMA state.
      2. Look up the current threshold via sliding window join.
      3. Flag anomaly if z_score > z_threshold OR value > threshold.
    """

    def __init__(
        self,
        half_life: float = 60.0,
        z_threshold: float = 3.0,
        join_window: float = 300.0,
        warmup_events: int = 5,
    ):
        self.z_threshold = z_threshold
        self._ewma_states: dict[str, EWMAState] = {}
        self._join = SlidingWindowJoin(window_size=join_window)
        self._half_life = half_life
        self._warmup = warmup_events

        self.alerts: list[AnomalyAlert] = []
        self.readings_processed: int = 0

    def process(self, event) -> Optional[AnomalyAlert]:
        if isinstance(event, ThresholdUpdate):
            self._join.ingest_threshold(event)
            return None

        if not isinstance(event, SensorReading):
            return None

        self.readings_processed += 1
        sid = event.sensor_id

        if sid not in self._ewma_states:
            self._ewma_states[sid] = EWMAState(
                half_life=self._half_life,
                warmup_events=self._warmup,
                z_threshold=self.z_threshold,
            )

        state = self._ewma_states[sid]
        z = state.update(event.value, event.event_time)
        threshold = self._join.lookup_threshold(event)

        if not state.is_warmed_up:
            return None

        z_anomaly = z is not None and abs(z) > self.z_threshold
        thresh_anomaly = threshold is not None and event.value > threshold

        if z_anomaly or thresh_anomaly:
            triggered = ("both" if z_anomaly and thresh_anomaly
                         else "z_score" if z_anomaly else "threshold")
            alert = AnomalyAlert(
                sensor_id=sid,
                value=event.value,
                event_time=event.event_time,
                ewma=state.ema,
                ewma_std=state.std,
                z_score=z or 0.0,
                threshold=threshold,
                triggered_by=triggered,
            )
            self.alerts.append(alert)
            return alert

        return None


# ---------------------------------------------------------------------------
# Stream generators
# ---------------------------------------------------------------------------

def generate_sensor_stream(
    sensors: list[str],
    duration: float = 3600.0,
    interval: float = 5.0,
    base_values: dict = None,
    noise_std: float = 2.0,
    anomaly_prob: float = 0.02,
    anomaly_magnitude: float = 15.0,
) -> list:
    """
    Generate a mixed stream of SensorReadings and ThresholdUpdates.
    Anomalies are random spikes with given probability.
    """
    rng = random.Random(42)
    events = []
    base_values = base_values or {s: rng.uniform(20, 80) for s in sensors}

    # Inject some threshold updates at the beginning and mid-stream
    for sensor in sensors:
        events.append(ThresholdUpdate(
            sensor_id=sensor,
            threshold=base_values[sensor] + 3 * noise_std + anomaly_magnitude * 0.7,
            event_time=0.0,
        ))

    # Mid-stream threshold tightening (simulates config change)
    for sensor in sensors[:len(sensors)//2]:
        events.append(ThresholdUpdate(
            sensor_id=sensor,
            threshold=base_values[sensor] + 2 * noise_std + anomaly_magnitude * 0.4,
            event_time=duration / 2,
        ))

    # Generate readings
    t = 0.0
    while t < duration:
        for sensor in sensors:
            jitter = rng.gauss(0, interval * 0.1)
            reading_time = t + jitter
            value = rng.gauss(base_values[sensor], noise_std)

            # Inject anomaly spike
            if rng.random() < anomaly_prob:
                value += rng.uniform(anomaly_magnitude * 0.8, anomaly_magnitude * 1.5)

            events.append(SensorReading(
                sensor_id=sensor,
                value=value,
                event_time=reading_time,
            ))
        t += interval

    events.sort(key=lambda e: e.event_time)
    return events


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo_ewma_comparison():
    """Compare fast vs slow EWMA decay on the same stream."""
    print("\n--- EWMA Decay Comparison ---")
    print("Same anomaly, three different half-life settings:\n")

    rng = random.Random(1)
    # Normal readings for 200s, then spike
    base = 50.0
    events_seq = [(t, rng.gauss(base, 2)) for t in range(0, 200, 5)]
    events_seq += [(200, 80.0)]  # anomaly spike
    events_seq += [(t, rng.gauss(base, 2)) for t in range(205, 300, 5)]

    half_lives = [10.0, 60.0, 300.0]
    labels = ["fast (10s)", "medium (60s)", "slow (300s)"]

    print(f"{'Time':>6} {'Value':>8} " + "".join(f"  EMA({l})" for l in labels))
    print("-" * 60)

    states = [EWMAState(half_life=hl, warmup_events=3) for hl in half_lives]
    for t, v in events_seq[::4] + [(200, 80.0)] + events_seq[-1:]:  # sample every 4
        for s in states:
            s.update(v, t)
        emas = [f"{s.ema:.1f}" if s.ema else "  n/a" for s in states]
        marker = " ← SPIKE" if v > 70 else ""
        print(f"{t:>6} {v:>8.1f} " + "".join(f"  {e:>8}" for e in emas) + marker)


def run_demo():
    print("=" * 70)
    print("EWMA Anomaly Detection + Sliding Window Join Demo")
    print("=" * 70)

    SENSORS = ["temp-01", "temp-02", "pressure-01", "vibration-01"]
    BASE = {"temp-01": 45.0, "temp-02": 52.0, "pressure-01": 101.3, "vibration-01": 30.0}

    print(f"\nGenerating 1-hour stream: {len(SENSORS)} sensors, 5s interval, 2% anomaly rate...")
    stream = generate_sensor_stream(
        sensors=SENSORS,
        duration=3600.0,
        interval=5.0,
        base_values=BASE,
        noise_std=2.5,
        anomaly_prob=0.02,
        anomaly_magnitude=18.0,
    )

    readings_count = sum(1 for e in stream if isinstance(e, SensorReading))
    threshold_count = sum(1 for e in stream if isinstance(e, ThresholdUpdate))
    print(f"Stream: {readings_count} readings + {threshold_count} threshold updates\n")

    detector = AnomalyDetector(
        half_life=60.0,
        z_threshold=3.0,
        join_window=300.0,
        warmup_events=5,
    )

    for event in stream:
        detector.process(event)

    print(f"Anomalies detected: {len(detector.alerts)}\n")
    print(f"{'Sensor':<15} {'Time':>8} {'Value':>8} {'EWMA':>8} {'Std':>6} "
          f"{'Z':>6} {'Thresh':>8} {'Trigger':<10}")
    print("-" * 75)
    for alert in detector.alerts[:20]:
        thresh_str = f"{alert.threshold:.1f}" if alert.threshold else "none"
        print(f"{alert.sensor_id:<15} {alert.event_time:>8.0f} "
              f"{alert.value:>8.2f} {alert.ewma:>8.2f} {alert.ewma_std:>6.2f} "
              f"{alert.z_score:>+6.2f} {thresh_str:>8} {alert.triggered_by:<10}")

    if len(detector.alerts) > 20:
        print(f"  ... and {len(detector.alerts) - 20} more")

    # Per-sensor breakdown
    print(f"\n--- Per-sensor anomaly breakdown ---")
    from collections import Counter
    by_sensor = Counter(a.sensor_id for a in detector.alerts)
    by_trigger = Counter(a.triggered_by for a in detector.alerts)
    for sensor, count in sorted(by_sensor.items()):
        print(f"  {sensor:<20}: {count} anomalies")
    print(f"\n  By trigger type: {dict(by_trigger)}")

    # Sliding window join demo
    print(f"\n--- Sliding Window Join Demo ---")
    print("Showing threshold lookup for a single sensor over time:\n")
    join = SlidingWindowJoin(window_size=120.0)

    # Feed some threshold updates
    join.ingest_threshold(ThresholdUpdate("sensor-X", 75.0, event_time=100.0))
    join.ingest_threshold(ThresholdUpdate("sensor-X", 65.0, event_time=250.0))
    join.ingest_threshold(ThresholdUpdate("sensor-X", 55.0, event_time=500.0))

    test_times = [50, 150, 220, 300, 400, 600]
    print(f"  {'Reading time':>14} {'Threshold joined':>18}")
    print(f"  {'-'*35}")
    for t in test_times:
        r = SensorReading("sensor-X", 70.0, t)
        thresh = join.lookup_threshold(r)
        thresh_str = f"{thresh:.1f}" if thresh else "None (outside window)"
        print(f"  t={t:>10.0f}   {thresh_str:>18}")

    demo_ewma_comparison()


if __name__ == "__main__":
    run_demo()
