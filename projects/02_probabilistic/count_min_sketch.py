"""
Prototype 2a: Count-Min Sketch — Approximate Frequency Estimation
=================================================================
A probabilistic data structure for estimating event frequencies in a stream
using sub-linear memory. Core use case: heavy hitter detection (top-K items).

Guarantees (with probability ≥ 1 - δ):
    estimate(x) ≤ true_count(x) + ε × N
    estimate(x) ≥ true_count(x)        (never undercounts)

where:
    ε = e / width          (error tolerance)
    δ = (1/e)^depth        (failure probability)
    N = total events seen

Choosing parameters:
    width  = ceil(e / ε)   e.g. width=2719 for ε=0.001
    depth  = ceil(ln(1/δ)) e.g. depth=5 for δ=0.006 (99.4% confidence)

No dependencies beyond the Python standard library.

Run:  python count_min_sketch.py
"""

from __future__ import annotations
import hashlib
import math
import random
import struct
from collections import Counter
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Count-Min Sketch
# ---------------------------------------------------------------------------

class CountMinSketch:
    """
    A d×w matrix of counters with d pairwise-independent hash functions.

    Parameters
    ----------
    width  : Number of columns (controls error magnitude).
    depth  : Number of rows/hash functions (controls failure probability).
    seed   : Random seed for hash function generation.
    """

    def __init__(self, width: int = 2719, depth: int = 5, seed: int = 42):
        self.width = width
        self.depth = depth
        self._table = [[0] * width for _ in range(depth)]
        self._total = 0
        # Generate (a, b) pairs for pairwise-independent hash functions
        rng = random.Random(seed)
        p = (1 << 31) - 1  # Mersenne prime
        self._hashes = [(rng.randint(1, p - 1), rng.randint(0, p - 1)) for _ in range(depth)]
        self._prime = p

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def _hash(self, item: str, row: int) -> int:
        """Map item to a column index for the given row."""
        # Use SHA-256 for the base hash, then apply a pairwise-independent transform
        h = int(hashlib.sha256(item.encode()).hexdigest(), 16) & 0x7FFFFFFF
        a, b = self._hashes[row]
        return ((a * h + b) % self._prime) % self.width

    def update(self, item: str, count: int = 1) -> None:
        """Increment all d counters for item by count."""
        self._total += count
        for row in range(self.depth):
            col = self._hash(item, row)
            self._table[row][col] += count

    def query(self, item: str) -> int:
        """Return the minimum of all d counter values — an upper-bound estimate."""
        return min(self._table[row][self._hash(item, row)] for row in range(self.depth))

    def merge(self, other: "CountMinSketch") -> "CountMinSketch":
        """Return a new sketch that is the element-wise sum (union of two streams)."""
        assert self.width == other.width and self.depth == other.depth
        result = CountMinSketch(self.width, self.depth)
        result._total = self._total + other._total
        for i in range(self.depth):
            for j in range(self.width):
                result._table[i][j] = self._table[i][j] + other._table[i][j]
        return result

    # ------------------------------------------------------------------
    # Heavy hitter detection
    # ------------------------------------------------------------------

    def heavy_hitters(self, candidates: list[str], top_n: int = 10) -> list[tuple[str, int]]:
        """
        Estimate counts for all candidates and return the top_n by estimated count.
        Note: the CMS cannot enumerate items it hasn't been told about — you must
        supply candidates from a separate reservoir or item set.
        """
        scored = [(item, self.query(item)) for item in candidates]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_n]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def error_rate(self) -> float:
        """Theoretical ε: maximum additive error as a fraction of total events."""
        return math.e / self.width

    @property
    def failure_prob(self) -> float:
        """Theoretical δ: probability that any single query exceeds the error bound."""
        return (1 / math.e) ** self.depth

    @property
    def memory_bytes(self) -> int:
        """Approximate memory used by the counter table (assuming 8-byte ints)."""
        return self.width * self.depth * 8

    def __repr__(self) -> str:
        return (
            f"CountMinSketch(width={self.width}, depth={self.depth}, "
            f"total={self._total}, ε={self.error_rate:.4f}, δ={self.failure_prob:.4f}, "
            f"~{self.memory_bytes // 1024}KB)"
        )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def generate_zipf_stream(n_events: int, n_items: int, exponent: float = 1.2) -> list[str]:
    """
    Generate a Zipf-distributed stream of item IDs.
    In a Zipf distribution, item rank k has frequency ∝ 1/k^exponent.
    This models web traffic, word frequencies, and click streams.
    """
    # Precompute Zipf probabilities
    weights = [1.0 / (k ** exponent) for k in range(1, n_items + 1)]
    total = sum(weights)
    probs = [w / total for w in weights]

    # Cumulative distribution for sampling
    cum = []
    running = 0.0
    for p in probs:
        running += p
        cum.append(running)

    def sample_item() -> str:
        r = random.random()
        lo, hi = 0, len(cum) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        return f"item-{lo + 1:05d}"

    return [sample_item() for _ in range(n_events)]


def run_demo():
    random.seed(42)
    N_EVENTS = 1_000_000
    N_ITEMS  = 10_000

    print("=" * 70)
    print(f"Count-Min Sketch Demo: {N_EVENTS:,} events, {N_ITEMS:,} distinct items")
    print("=" * 70)

    print(f"\nGenerating Zipf-distributed stream (exponent=1.2)...")
    stream = generate_zipf_stream(N_EVENTS, N_ITEMS, exponent=1.2)
    exact_counts = Counter(stream)
    top10_exact = exact_counts.most_common(10)

    # --- Exact (baseline) ---
    exact_mem = N_ITEMS * (len("item-00000") + 8)  # key + int64

    # --- CMS ---
    # Parameters for ε=0.001 (0.1% of N), δ≈0.007 (99.3% confidence)
    cms = CountMinSketch(width=2719, depth=5)
    print(f"CMS parameters: {cms}")
    print(f"Processing stream...")

    for item in stream:
        cms.update(item)

    # Query top-10 candidates (we use the exact keys as candidates — in production
    # you'd use a separate Count Sketch or sampled reservoir)
    candidates = [f"item-{k:05d}" for k in range(1, N_ITEMS + 1)]
    top10_cms = cms.heavy_hitters(candidates, top_n=10)

    print(f"\n{'Rank':<6} {'Item':<15} {'Exact':>10} {'CMS Est':>10} {'Error':>10} {'Error%':>8}")
    print("-" * 65)
    for i, ((exact_item, exact_cnt), (cms_item, cms_cnt)) in enumerate(
        zip(top10_exact, top10_cms), 1
    ):
        error = cms_cnt - exact_cnt
        error_pct = 100.0 * error / exact_cnt
        match = "✓" if exact_item == cms_item else "✗"
        print(f"{i:<6} {exact_item:<15} {exact_cnt:>10,} {cms_cnt:>10,} "
              f"{error:>+10,} {error_pct:>+7.2f}% {match}")

    # Memory comparison
    cms_mem = cms.memory_bytes
    print(f"\nMemory comparison:")
    print(f"  Exact counter dict : ~{exact_mem / 1024:.0f} KB  ({N_ITEMS:,} entries)")
    print(f"  Count-Min Sketch   : ~{cms_mem / 1024:.0f} KB  ({cms.width}×{cms.depth} matrix)")
    print(f"  Compression ratio  :  {exact_mem / cms_mem:.1f}×")

    print(f"\nError bounds:")
    print(f"  Max additive error : ε×N = {cms.error_rate:.4f} × {N_EVENTS:,} "
          f"= {cms.error_rate * N_EVENTS:,.0f} counts")
    print(f"  Failure probability: δ = {cms.failure_prob:.4f} "
          f"({(1 - cms.failure_prob) * 100:.1f}% confidence)")

    # --- Merge demo ---
    print(f"\n--- Merge demo: two half-streams merged ---")
    cms_a = CountMinSketch(width=2719, depth=5)
    cms_b = CountMinSketch(width=2719, depth=5)
    half = len(stream) // 2
    for item in stream[:half]:
        cms_a.update(item)
    for item in stream[half:]:
        cms_b.update(item)
    merged = cms_a.merge(cms_b)

    # Compare merged top-3 with full sketch top-3
    top3_merged = merged.heavy_hitters(candidates[:100], top_n=3)
    top3_full   = cms.heavy_hitters(candidates[:100], top_n=3)
    print("  Merged top-3:", top3_merged)
    print("  Full   top-3:", top3_full)
    print("  Match:", top3_merged == top3_full)


if __name__ == "__main__":
    run_demo()
