"""
Prototype 2b: HyperLogLog — Cardinality Estimation
====================================================
Estimates the number of distinct elements in a stream using O(log log N) memory.

Core insight: in a stream of hashed values, the maximum number of leading zeros
in any hash is statistically correlated with log2(cardinality). HyperLogLog
improves accuracy by partitioning elements into m buckets and averaging.

Standard error: 1.04 / sqrt(m)
  m=16    buckets  →  26% error
  m=64    buckets  →  13% error
  m=256   buckets  →  6.5% error
  m=1024  buckets  →  3.25% error
  m=4096  buckets  →  1.6% error  (requires 4KB)
  m=65536 buckets  →  0.4% error  (requires 64KB)

This implements HyperLogLog++ corrections (Google, 2013):
  - Small-range correction (linear counting when estimated cardinality is low)
  - Large-range correction (not needed below 2^32)

No dependencies beyond the Python standard library.

Run:  python hyperloglog.py
"""

from __future__ import annotations
import hashlib
import math
import random
import struct


# ---------------------------------------------------------------------------
# HyperLogLog
# ---------------------------------------------------------------------------

class HyperLogLog:
    """
    HyperLogLog cardinality estimator.

    Parameters
    ----------
    precision : int in [4, 16]. Controls number of buckets m = 2^precision.
                Higher precision → lower error but more memory.
    """

    # Bias correction constant α_m
    _ALPHA = {
        16: 0.673, 32: 0.697, 64: 0.709,
    }
    _ALPHA_DEFAULT = 0.7213  # asymptotic value for m >= 128

    def __init__(self, precision: int = 12):
        if not 4 <= precision <= 16:
            raise ValueError("precision must be in [4, 16]")
        self.precision = precision
        self.m = 1 << precision          # number of buckets = 2^precision
        self._registers = [0] * self.m  # M[j] = max leading zeros seen in bucket j

        # bias correction constant
        if self.m in self._ALPHA:
            self._alpha = self._ALPHA[self.m]
        else:
            self._alpha = self._ALPHA_DEFAULT / (1 + 1.079 / self.m)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def _hash(self, item: str) -> int:
        """64-bit hash of item."""
        digest = hashlib.sha256(item.encode()).digest()
        return struct.unpack(">Q", digest[:8])[0]

    def add(self, item: str) -> None:
        """Add an item to the sketch."""
        h = self._hash(item)
        # Top `precision` bits → bucket index
        bucket = h >> (64 - self.precision)
        # Remaining bits → count leading zeros + 1
        remainder = h & ((1 << (64 - self.precision)) - 1)
        # Count leading zeros in the remainder (within 64-precision bits)
        rho = self._leading_zeros(remainder, 64 - self.precision) + 1
        if rho > self._registers[bucket]:
            self._registers[bucket] = rho

    @staticmethod
    def _leading_zeros(value: int, bit_length: int) -> int:
        """Count leading zeros in a `bit_length`-wide integer."""
        if value == 0:
            return bit_length
        return bit_length - value.bit_length()

    def count(self) -> int:
        """Estimate the number of distinct elements seen."""
        m = self.m
        # Raw harmonic mean estimate
        Z = sum(2.0 ** (-r) for r in self._registers)
        E = self._alpha * m * m / Z

        # Small range correction (linear counting)
        if E <= 2.5 * m:
            V = self._registers.count(0)  # number of zero registers
            if V > 0:
                return round(m * math.log(m / V))

        # Large range correction (not needed for 64-bit hashes at normal cardinalities)

        return round(E)

    def merge(self, other: "HyperLogLog") -> "HyperLogLog":
        """Union: estimate cardinality of set A ∪ B."""
        assert self.precision == other.precision
        result = HyperLogLog(self.precision)
        result._registers = [max(a, b) for a, b in zip(self._registers, other._registers)]
        return result

    # ------------------------------------------------------------------
    # Memory / properties
    # ------------------------------------------------------------------

    @property
    def standard_error(self) -> float:
        return 1.04 / math.sqrt(self.m)

    @property
    def memory_bytes(self) -> int:
        """Each register needs ~5 bits; we store as bytes here for simplicity."""
        return self.m  # 1 byte per register (actual implementations pack to 6-bit)

    def __repr__(self) -> str:
        return (
            f"HyperLogLog(precision={self.precision}, m={self.m}, "
            f"error={self.standard_error:.2%}, mem={self.memory_bytes}B)"
        )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo():
    random.seed(42)

    print("=" * 70)
    print("HyperLogLog Cardinality Estimation Demo")
    print("=" * 70)

    # --- Accuracy vs precision sweep ---
    print("\n1. Accuracy vs Precision (1M unique items)")
    print(f"{'Precision':>10} {'Buckets':>10} {'Memory':>10} {'Std Error':>12} "
          f"{'Estimate':>12} {'Exact':>10} {'Rel Error':>10}")
    print("-" * 80)

    N = 1_000_000
    items = [f"user-{i}" for i in range(N)]

    for p in [6, 8, 10, 12, 14]:
        hll = HyperLogLog(precision=p)
        for item in items:
            hll.add(item)
        est = hll.count()
        rel_err = (est - N) / N
        print(f"{p:>10} {hll.m:>10,} {hll.memory_bytes:>8}B "
              f"{hll.standard_error:>11.2%} {est:>12,} {N:>10,} {rel_err:>+10.2%}")

    # --- Streaming cardinality over time ---
    print("\n2. Streaming Unique User Count (events with repeated users)")
    hll = HyperLogLog(precision=12)
    exact_seen = set()

    # 500K events, users drawn from pool of 50K unique users (Zipf)
    user_pool = [f"user-{i:06d}" for i in range(50_000)]
    weights = [1.0 / (i + 1) for i in range(len(user_pool))]
    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    checkpoints = [10_000, 50_000, 100_000, 250_000, 500_000]
    events_seen = 0

    print(f"{'Events':>10} {'HLL Est':>12} {'Exact':>10} {'Rel Error':>12}")
    print("-" * 48)

    cp_idx = 0
    while events_seen < 500_000:
        # Sample a user (Zipf-like: popular users appear more often)
        user = random.choices(user_pool, weights=weights, k=1)[0]
        hll.add(user)
        exact_seen.add(user)
        events_seen += 1

        if cp_idx < len(checkpoints) and events_seen == checkpoints[cp_idx]:
            est = hll.count()
            exact = len(exact_seen)
            rel_err = (est - exact) / exact
            print(f"{events_seen:>10,} {est:>12,} {exact:>10,} {rel_err:>+11.2%}")
            cp_idx += 1

    # --- Merge demo ---
    print("\n3. Merge: Union of Two Disjoint Streams")
    hll_a = HyperLogLog(precision=12)
    hll_b = HyperLogLog(precision=12)

    stream_a = [f"user-A-{i}" for i in range(100_000)]
    stream_b = [f"user-B-{i}" for i in range(80_000)]

    for item in stream_a:
        hll_a.add(item)
    for item in stream_b:
        hll_b.add(item)

    merged = hll_a.merge(hll_b)
    exact_union = len(set(stream_a) | set(stream_b))

    print(f"  Stream A distinct: {hll_a.count():,}  (exact: {len(stream_a):,})")
    print(f"  Stream B distinct: {hll_b.count():,}  (exact: {len(stream_b):,})")
    print(f"  Merged union est : {merged.count():,}  (exact: {exact_union:,})")
    print(f"  Merge rel. error : {(merged.count() - exact_union) / exact_union:+.2%}")

    # --- Memory comparison ---
    print("\n4. Memory: HLL vs Exact Set")
    n_users = 10_000_000
    hll_12 = HyperLogLog(precision=12)
    print(f"  Exact set ({n_users:,} UUIDs) : ~{n_users * 36 // 1024 // 1024} MB")
    print(f"  HLL precision=12            :  {hll_12.memory_bytes} bytes ({hll_12.memory_bytes}B)")
    print(f"  Compression ratio           :  {n_users * 36 / hll_12.memory_bytes:,.0f}×")
    print(f"  Expected std error          :  {hll_12.standard_error:.2%}")


if __name__ == "__main__":
    run_demo()
