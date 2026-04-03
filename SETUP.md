# Stock Picker — Setup Guide

This guide walks you through getting the stock picker running on a new machine with Claude Code (nanoclaw).

---

## Prerequisites

- **Claude Code** installed and authenticated (`claude` CLI available)
- **Python >= 3.10**
- **`uv`** package manager: https://docs.astral.sh/uv/getting-started/installation/
- **Git**

---

## 1. Clone the Repository

```bash
git clone git@github.com:javastarchild/stock_picker.git
cd stock_picker
```

Or via HTTPS if you haven't set up SSH keys:

```bash
git clone https://github.com/javastarchild/stock_picker.git
cd stock_picker
```

---

## 2. Install Dependencies

```bash
uv sync
```

This creates a `.venv/` and installs all Python dependencies (yfinance, statsmodels, nltk, pandas, etc.).

---

## 3. (Optional) Set News API Key

News sentiment analysis requires a NewsAPI key. Without it, the analysis runs fine using neutral sentiment.

```bash
export NEWSAPI_KEY=your_key_here
```

To make it permanent, add it to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.).

Get a free key at https://newsapi.org

---

## 4. Open in Claude Code

From inside the cloned directory:

```bash
claude
```

The project ships with two Claude Code slash commands in `.claude/commands/`:

| Command | Description |
|---|---|
| `/run-stock-picker [industry] [months]` | Run the full analysis pipeline |
| `/stock-report` | Display the most recent forecast report |

These are **project-level commands** — they activate automatically when Claude Code is opened in this directory. No global installation needed.

---

## 5. Run Your First Analysis

In a Claude Code session:

```
/run-stock-picker technology 6
```

This will:
1. Fetch the S&P 500 technology tickers
2. Download 6 months of price history via yfinance
3. Run SARIMAX forecasts for 7 business days
4. Write a CSV report + summary to `report/`

Then view the results:

```
/stock-report
```

---

## 6. Run Tests

```bash
uv run pytest tests/
```

---

## Project Structure

```
stock_picker/
├── stock_picker_agents.py     # All agents + orchestrator (core logic)
├── pyproject.toml             # Dependencies
├── uv.lock                    # Locked dependency versions
├── .claude/
│   └── commands/
│       ├── run-stock-picker.md   # /run-stock-picker slash command
│       └── stock-report.md       # /stock-report slash command
├── CLAUDE.md                  # Claude Code project instructions
├── tests/
│   └── test_stock_picker.py
└── report/                    # Generated reports (gitignored)
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'yfinance'`**
Run via `uv run python` instead of bare `python`. The slash commands handle this automatically.

**Wikipedia 403 on constituent fetch**
Normal — the agent falls back to GitHub CSV automatically.

**Fewer than 30 days of price history**
Tickers with insufficient history are skipped with `success=False` in the results. Increase `lookback_months` if needed.

**`.cache/sp500_constituents.csv` is stale**
Delete it to force a fresh fetch:
```bash
rm .cache/sp500_constituents.csv
```
