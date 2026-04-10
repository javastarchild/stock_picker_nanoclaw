# Real-Time Stateful Stream Aggregators
## Prototype Suite — SOTA Approaches

A hands-on exploration of modern stateful stream processing patterns.
Five self-contained prototypes, each highlighting a distinct SOTA technique.
Prototypes 1–3 and 5 are pure Python — no infrastructure required.

---

## What Is a Stateful Stream Aggregator?

A system that processes **continuous, unbounded event streams** while maintaining
**state** across time to compute aggregates (counts, sums, averages, top-K, joins)
that are impossible with per-event stateless processing.

The core challenge: you can never have all the data at once, events arrive
out-of-order, state must survive failures, and results must be correct.

---

## Prototype Map

| # | File | Core Concept | Framework | Run |
|---|------|-------------|-----------|-----|
| 1 | `01_watermark_windowing/windowing_engine.py` | Tumbling/sliding windows, watermarks, late events | Pure Python | `python windowing_engine.py` |
| 2a | `02_probabilistic/count_min_sketch.py` | Count-Min Sketch (heavy hitters) | Pure Python | `python count_min_sketch.py` |
| 2b | `02_probabilistic/hyperloglog.py` | HyperLogLog (cardinality estimation) | Pure Python | `python hyperloglog.py` |
| 3 | `03_session_aggregation/session_aggregator.py` | Session windows, per-key timers, session merging | Pure Python | `python session_aggregator.py` |
| 4 | `04_incremental_view/seed.py` | Incremental Materialized Views (IVM), streaming SQL | RisingWave (Docker) | See below |
| 5 | `05_ewma_anomaly/ewma_anomaly.py` | EWMA, sliding window join, anomaly detection | Pure Python | `python ewma_anomaly.py` |

---

## Quick Start

```bash
# Run pure-Python prototypes immediately (no setup)
python 01_watermark_windowing/windowing_engine.py
python 02_probabilistic/count_min_sketch.py
python 02_probabilistic/hyperloglog.py
python 03_session_aggregation/session_aggregator.py
python 05_ewma_anomaly/ewma_anomaly.py

# Prototype 4 requires Docker
cd 04_incremental_view
docker compose up -d
pip install psycopg2-binary
python seed.py
```

---

## Prototype Details

### 1. Watermark Windowing Engine (`01_watermark_windowing/`)

**What it shows:** The foundational mechanics every streaming framework hides from you.

- **Event time vs. processing time**: Events carry their own timestamp, independent of when they arrive.
- **Watermark**: A monotonically advancing `W(t)` asserting "no event with `event_time < W(t)` will arrive." Windows close when the watermark passes their end boundary.
- **Tumbling windows**: Non-overlapping fixed-size buckets. Each event belongs to exactly one window.
- **Sliding windows**: Overlapping windows. Each event belongs to `size/slide` windows simultaneously.
- **Late event side output**: Events arriving after the watermark are routed to a side output (not silently dropped).

Three demos:
1. Watermark progression trace (manually crafted events, step-by-step)
2. Out-of-order stream with ~5% very late events
3. Sliding windows (20s/5s) showing each event landing in 4 overlapping windows

---

### 2a. Count-Min Sketch (`02_probabilistic/count_min_sketch.py`)

**What it shows:** Approximate frequency counting with provable error bounds in sub-linear memory.

A `d×w` counter matrix with `d` hash functions. Updating item `x` increments `table[i][hash_i(x)]` for each row. Querying returns `min_i(table[i][hash_i(x)])` — an upper-bound estimate. The minimum corrects for hash collisions.

**Guarantees:** With probability `≥ 1 - δ`:
```
true_count(x) ≤ estimate(x) ≤ true_count(x) + ε × N
```
where `ε = e/width`, `δ = (1/e)^depth`, `N` = total events.

Demo: 1M Zipf-distributed URL click events. Find top-10 heavy hitters. Compare memory: `~106KB` (CMS) vs `~78KB` (exact dict with only 10K items — but CMS scales to billions of unique items while dict does not).

Also shows **mergeable sketches**: two half-streams processed independently, merged exactly as if processed together.

---

### 2b. HyperLogLog (`02_probabilistic/hyperloglog.py`)

**What it shows:** Counting distinct elements in a stream using `O(log log N)` memory.

Partitions items into `m = 2^precision` buckets via the high-order hash bits. For each bucket, tracks the maximum number of leading zeros in the hash — statistically correlated with `log2` of the cardinality of items mapped to that bucket. Combines buckets via harmonic mean with bias corrections.

**Standard error:** `1.04 / sqrt(m)`
- `precision=12` → 4096 buckets, 4KB, **±1.6% error**
- `precision=14` → 16384 buckets, 16KB, **±0.8% error**

Demo: 10M unique users → 4KB HLL vs **~360MB** for an exact set. Merge of two disjoint streams.

---

### 3. Session Window Aggregation (`03_session_aggregation/`)

**What it shows:** The hardest window type — data-dependent boundaries with session merging.

Sessions are per-key (per-user). A session ends when no event for that user arrives within `gap_timeout` seconds. This prototype implements:

- **Dynamic window boundaries**: No fixed start/end — the window grows as events arrive.
- **Session merging**: A late event that bridges two previously separate sessions merges them into one.
- **Per-key state management**: Each user has an independent list of open sessions.
- **Metrics per session**: event count, dwell time, pages visited, revenue, conversion flag.

Demo: 10 users, 500 events, `gap_timeout=30s`. Shows session summaries with conversion rates and revenue rollup. Explicit merge demo shows bridging event combining two sessions.

---

### 4. Incremental Materialized View (`04_incremental_view/`)

**What it shows:** Streaming SQL with delta propagation — only changed rows recompute.

Uses **RisingWave**, a cloud-native streaming database with PostgreSQL wire protocol. When a row is inserted into `orders`, only the affected `category` row in `revenue_by_category` is updated — not a full GROUP BY recompute.

Schema:
```sql
orders(order_id, product_id, user_id, quantity, order_time)
products(product_id, name, category, unit_price)

CREATE MATERIALIZED VIEW revenue_by_category AS
    SELECT category, COUNT(*), SUM(quantity * unit_price), AVG(...)
    FROM orders JOIN products USING (product_id)
    GROUP BY category;
```

Demo shows:
1. Initial batch insert → view populates
2. Second batch → only delta rows update
3. Price change (DELETE + INSERT on products) → view re-derives from join
4. IVM latency benchmark: average time from INSERT to visible view update

**Start RisingWave:**
```bash
cd 04_incremental_view && docker compose up -d
```

**Explore with psql:**
```bash
psql -h localhost -p 4566 -U root -d dev
SELECT * FROM revenue_by_category;
```

---

### 5. EWMA Anomaly Detection + Sliding Window Join (`05_ewma_anomaly/`)

**What it shows:** Two advanced stateful patterns combined.

**Time-continuous EWMA:**
```
λ = exp(-α × Δt)     # decay factor; larger Δt → more decay
EMA(t) = v(t) + EMA(t_prev) × λ
EMVAR(t) = (1-λ)(v(t) - EMA(t_prev))² + λ × EMVAR(t_prev)
```
Unlike fixed windows, EWMA requires `O(1)` state per key and handles irregular timestamps correctly. `half_life` controls responsiveness.

**Sliding window join (two streams):**
For each `SensorReading`, finds the most recent `ThresholdUpdate` for the same sensor within `[reading_time - W, reading_time]`. This is the "apply current config to each event" pattern — common in dynamic thresholding, feature store lookups, and policy enforcement.

**Anomaly detection:**
A reading is flagged if:
- `|z_score| > threshold` (EWMA-based), OR
- `value > absolute_threshold` (from the joined threshold stream)

Demo: 4 sensors, 1-hour stream, 5s intervals, 2% injected anomaly rate. Shows per-sensor breakdown and triggered-by classification. Includes EWMA decay comparison (fast/medium/slow half-life on same spike).

---

## SOTA Framework Reference

| Framework | Model | Language | State | Best For |
|-----------|-------|----------|-------|----------|
| **Apache Flink 2.0** | Dataflow, exactly-once | Java/Python | RocksDB/ForSt | Production at scale, low latency |
| **RisingWave** | Streaming SQL DB | Rust | Hummock (S3-backed) | SQL queries over streams, cloud-native |
| **Materialize** | IVM, Differential Dataflow | Rust | Timely Dataflow | Always-fresh operational views |
| **Pathway** | Incremental computation | Python/Rust | In-process | Python ML pipelines, no-infra dev |
| **Kafka Streams** | KTable/KStream | Java | RocksDB + Kafka | JVM apps already on Kafka |
| **Feldera** | DBSP (full SQL IVM) | Rust | In-memory | Full SQL semantics incrementally |
| **Spark Structured Streaming** | Micro-batch | Scala/Python | Checkpointed state | Unified batch+stream on Spark |

---

## Key Concepts Cheatsheet

| Concept | One-line definition |
|---------|-------------------|
| **Watermark** | Monotone timestamp asserting "no earlier event will arrive" — triggers window closing |
| **Tumbling window** | Non-overlapping fixed buckets; each event in exactly one window |
| **Sliding window** | Overlapping windows; each event in `size/slide` windows |
| **Session window** | Per-key gap-based; size determined by data, not clock |
| **Exactly-once** | Each event affects aggregate state exactly once despite failures |
| **Count-Min Sketch** | Approximate frequency counter; `O(ε⁻¹ log δ⁻¹)` space |
| **HyperLogLog** | Approximate cardinality estimator; `O(log log N)` space |
| **EWMA** | Exponentially weighted moving average; time-continuous version handles irregular timestamps |
| **IVM** | Incremental View Maintenance — update only the changed rows in a materialized view |
| **Sliding window join** | Join two event streams over overlapping time windows |

---

## References

- [Apache Flink 2.0 — Disaggregated State Management (VLDB 2025)](https://www.vldb.org/pvldb/vol18/p4846-mei.pdf)
- [RisingWave Architecture](https://docs.risingwave.com/get-started/architecture)
- [DBSP: Automatic IVM for Rich Query Languages (VLDB Journal 2025)](https://link.springer.com/article/10.1007/s00778-025-00922-y)
- [Pathway: Python-native incremental computation](https://arxiv.org/abs/2307.13116)
- [Materialize: Always-fresh materialized views](https://materialize.com/blog-architecture/)
- [Count-Min Sketch paper (Cormode & Muthukrishnan, 2005)](http://dimacs.rutgers.edu/~graham/pubs/papers/cm-full.pdf)
- [HyperLogLog++ (Google, 2013)](https://research.google/pubs/hyperloglog-in-practice-algorithmic-engineering-of-a-state-of-the-art-cardinality-estimation-algorithm/)
- [Data Streaming Landscape 2026 (Kai Waehner)](https://www.kai-waehner.de/blog/2025/12/05/the-data-streaming-landscape-2026/)
