"""
Prototype 4: Incremental Materialized View with RisingWave
===========================================================
Demonstrates Incremental View Maintenance (IVM) using RisingWave — a
PostgreSQL-wire-compatible streaming SQL database.

Key concepts shown:
  - Source tables that accept streaming inserts
  - MATERIALIZED VIEWs that update incrementally (only the changed rows propagate)
  - Multi-table streaming join with GROUP BY aggregation
  - INSERT, UPDATE (via DELETE+INSERT), and the view reflects changes in <100ms
  - Querying the view with standard psql/psycopg2 — no special streaming API

Schema: e-commerce revenue analysis
  orders(order_id, product_id, user_id, quantity, order_time)
  products(product_id, name, category, unit_price)

Materialized View: revenue_by_category
  SELECT category, COUNT(*) as order_count, SUM(quantity * unit_price) AS revenue
  FROM orders JOIN products USING (product_id)
  GROUP BY category

Prerequisites:
  docker compose up -d       (start RisingWave)
  pip install psycopg2-binary (Python PostgreSQL client)

Run:  python seed.py
"""

import time
import random
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Install psycopg2-binary: pip install psycopg2-binary")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

CONN_PARAMS = {
    "host": "localhost",
    "port": 4566,
    "user": "root",
    "password": "",
    "database": "dev",
}

def connect(retries: int = 10, delay: float = 2.0):
    for i in range(retries):
        try:
            conn = psycopg2.connect(**CONN_PARAMS)
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            if i == retries - 1:
                raise
            print(f"  Waiting for RisingWave... ({i+1}/{retries})")
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

DDL = """
-- Source tables (accept streaming inserts)
CREATE TABLE IF NOT EXISTS products (
    product_id  INT PRIMARY KEY,
    name        VARCHAR,
    category    VARCHAR,
    unit_price  NUMERIC(10,2)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    INT PRIMARY KEY,
    product_id  INT,
    user_id     INT,
    quantity    INT,
    order_time  TIMESTAMP
);

-- Materialized view: incrementally maintained revenue by category
-- RisingWave re-evaluates only the rows affected by each INSERT/UPDATE/DELETE
CREATE MATERIALIZED VIEW IF NOT EXISTS revenue_by_category AS
    SELECT
        p.category,
        COUNT(o.order_id)                   AS order_count,
        SUM(o.quantity * p.unit_price)      AS revenue,
        AVG(o.quantity * p.unit_price)      AS avg_order_value
    FROM orders o
    JOIN products p ON o.product_id = p.product_id
    GROUP BY p.category;

-- Additional view: top products by revenue
CREATE MATERIALIZED VIEW IF NOT EXISTS top_products AS
    SELECT
        p.product_id,
        p.name,
        p.category,
        COUNT(o.order_id)               AS order_count,
        SUM(o.quantity)                 AS units_sold,
        SUM(o.quantity * p.unit_price)  AS revenue
    FROM orders o
    JOIN products p ON o.product_id = p.product_id
    GROUP BY p.product_id, p.name, p.category
    ORDER BY revenue DESC;
"""

TEARDOWN = """
DROP MATERIALIZED VIEW IF EXISTS top_products;
DROP MATERIALIZED VIEW IF EXISTS revenue_by_category;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
"""


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

PRODUCT_CATALOG = [
    (1,  "Pro Laptop 16\"",       "Electronics",   1299.99),
    (2,  "USB-C Hub 10-in-1",     "Electronics",     49.99),
    (3,  "Mechanical Keyboard",   "Electronics",    129.99),
    (4,  "4K Webcam",             "Electronics",     89.99),
    (5,  "Standing Desk",         "Furniture",      599.99),
    (6,  "Ergonomic Chair",       "Furniture",      449.99),
    (7,  "Desk Lamp LED",         "Furniture",       39.99),
    (8,  "Python Crash Course",   "Books",           29.99),
    (9,  "Designing Data-Intensive Apps", "Books",   54.99),
    (10, "The Pragmatic Programmer", "Books",        49.99),
]


def insert_products(cur):
    cur.executemany(
        "INSERT INTO products VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        PRODUCT_CATALOG
    )


def insert_orders(cur, orders: list[tuple]):
    cur.executemany(
        "INSERT INTO orders VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        orders
    )


def generate_orders(n: int, start_id: int = 1) -> list[tuple]:
    rng = random.Random(42 + start_id)
    orders = []
    product_ids = [p[0] for p in PRODUCT_CATALOG]
    weights = [5, 8, 6, 7, 3, 3, 4, 9, 6, 5]  # relative popularity
    for i in range(n):
        product_id = rng.choices(product_ids, weights=weights, k=1)[0]
        orders.append((
            start_id + i,
            product_id,
            rng.randint(1, 1000),  # user_id
            rng.randint(1, 3),     # quantity
            f"2026-04-09 {rng.randint(0,23):02d}:{rng.randint(0,59):02d}:00",
        ))
    return orders


def query_view(cur, view: str) -> list[dict]:
    cur.execute(f"SELECT * FROM {view}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def print_revenue(rows: list[dict], title: str):
    print(f"\n  {title}")
    print(f"  {'Category':<20} {'Orders':>8} {'Revenue':>12} {'Avg Order':>12}")
    print(f"  {'-'*56}")
    for r in sorted(rows, key=lambda x: -float(x.get('revenue', 0))):
        print(f"  {r['category']:<20} {r['order_count']:>8} "
              f"${float(r['revenue']):>11,.2f} ${float(r['avg_order_value']):>11,.2f}")


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

def run_demo():
    print("=" * 70)
    print("Incremental Materialized View Demo — RisingWave")
    print("=" * 70)

    print("\nConnecting to RisingWave at localhost:4566...")
    conn = connect()
    cur = conn.cursor()

    # --- Setup ---
    print("Setting up schema (teardown + recreate)...")
    for stmt in TEARDOWN.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            cur.execute(stmt)

    # --- Seed products ---
    insert_products(cur)
    print(f"Inserted {len(PRODUCT_CATALOG)} products.")

    # --- Initial batch of orders ---
    batch1 = generate_orders(100, start_id=1)
    insert_orders(cur, batch1)
    print(f"\nInserted batch 1: {len(batch1)} orders.")
    time.sleep(0.5)  # Allow view to update

    rows = query_view(cur, "revenue_by_category")
    print_revenue(rows, "revenue_by_category after batch 1:")

    # --- Add more orders ---
    batch2 = generate_orders(50, start_id=101)
    insert_orders(cur, batch2)
    print(f"\nInserted batch 2: {len(batch2)} more orders.")
    time.sleep(0.5)

    rows = query_view(cur, "revenue_by_category")
    print_revenue(rows, "revenue_by_category after batch 2 (incremental update):")

    # --- Price update: update the standing desk price ---
    print("\nUpdating 'Standing Desk' price: $599.99 → $499.99")
    print("(RisingWave propagates the delta — only affected rows recompute)")
    cur.execute("""
        DELETE FROM products WHERE product_id = 5;
        INSERT INTO products VALUES (5, 'Standing Desk', 'Furniture', 499.99);
    """)
    time.sleep(0.5)

    rows = query_view(cur, "revenue_by_category")
    print_revenue(rows, "revenue_by_category after price update:")

    # --- Top products ---
    print("\n  Top 5 products by revenue:")
    cur.execute("SELECT name, category, order_count, units_sold, revenue FROM top_products LIMIT 5")
    rows = cur.fetchall()
    print(f"  {'Product':<35} {'Category':<15} {'Orders':>7} {'Units':>7} {'Revenue':>12}")
    print(f"  {'-'*80}")
    for row in rows:
        print(f"  {row[0]:<35} {row[1]:<15} {row[2]:>7} {row[3]:>7} ${float(row[4]):>11,.2f}")

    # --- Latency benchmark ---
    print("\n--- IVM Latency Benchmark ---")
    print("Measuring time from INSERT to visible view update...")
    latencies = []
    for i in range(10):
        order_id = 200 + i
        t0 = time.perf_counter()
        cur.execute(
            "INSERT INTO orders VALUES (%s, %s, %s, %s, %s)",
            (order_id, 1, 999, 1, "2026-04-09 12:00:00")
        )
        # Poll until the view reflects the new order
        for _ in range(50):
            cur.execute("SELECT SUM(order_count) FROM revenue_by_category")
            count = cur.fetchone()[0]
            if count and count >= 150 + i + 1:
                break
            time.sleep(0.01)
        latency = (time.perf_counter() - t0) * 1000
        latencies.append(latency)

    avg_latency = sum(latencies) / len(latencies)
    print(f"  Average IVM update latency: {avg_latency:.1f}ms over {len(latencies)} samples")
    print(f"  Min: {min(latencies):.1f}ms  Max: {max(latencies):.1f}ms")

    cur.close()
    conn.close()
    print("\nDone. RisingWave container still running — connect with:")
    print("  psql -h localhost -p 4566 -U root -d dev")
    print("  SELECT * FROM revenue_by_category;")


if __name__ == "__main__":
    run_demo()
