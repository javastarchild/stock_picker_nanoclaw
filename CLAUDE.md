# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
# Install dependencies (requires Python >=3.10)
uv sync
```

`newsapi` is an optional runtime dependency not in `pyproject.toml`. Set `NEWSAPI_KEY` in the environment to enable news/sentiment; without it the analysis runs with neutral sentiment (`sentiment_score=0`).

## Commands

```bash
# Run all tests (always via uv run to pick up the venv)
uv run pytest tests/

# Run a single test
uv run pytest tests/test_stock_picker.py::test_normalize_dataframe_basic

# Run the CLI interactively
uv run python stock_picker_agents.py

# Launch Jupyter notebook
jupyter notebook
```

## Slash Commands

The project ships two Claude Code slash commands in `.claude/commands/`:

- `/run-stock-picker [industry] [months]` — runs the full analysis pipeline (default: `technology`, 6 months) and prints the report path + ticker success summary.
- `/stock-report` — displays the newest `*_summary.txt` and first 20 rows of the newest CSV from `report/`.

These are project-level commands active whenever Claude Code is opened in this directory.

## Architecture

The core logic lives in `stock_picker_agents.py`. Everything is organized around a multi-agent pipeline:

**Data classes** (`AnalysisConfig`, `StockData`, `NewsData`, `SentimentData`, `ForecastData`) — typed containers passed between agents.

**Agents** — each extends `BaseAgent(ABC)` and implements `execute()`:
- `DataSourceAgent` — fetches S&P 500 constituents (Wikipedia → GitHub CSV fallbacks → hardcoded list), caches results in `.cache/sp500_constituents.csv`
- `StockDataAgent` — downloads OHLCV data via `yfinance`; `execute_batch()` does a single multi-ticker download
- `NewsAgent` — calls NewsAPI; returns empty `NewsData` gracefully if key is missing
- `SentimentAgent` — VADER sentiment analysis; auto-downloads NLTK lexicon if needed
- `ForecastAgent` — fits SARIMAX(1,1,1) on adjusted close price with sentiment as exogenous variable, forecasts `config.forecast_days` business days
- `ReportAgent` — pivots results to one-row-per-ticker CSV + plain-text summary under `report/`

**Orchestrator** (`StockAnalysisOrchestrator`) — wires all agents together in `run_analysis(industry, lookback_months)`.

**CLI** (`StockAnalysisCLI`) — wraps the orchestrator with `run_interactive()` (prompts stdin) or `run_batch()` (programmatic).

**Factory functions** — `create_custom_config(**kwargs)` and `create_orchestrator(config)` for quick setup.

Notebooks (`stock-picker.ipynb`, `stock_prediction_checker.ipynb`, etc.) are exploratory and call into the same agents/orchestrator defined in `stock_picker_agents.py`.

## Key Behaviours

- `ForecastAgent` requires ≥30 trading days of price history; tickers with less are skipped with `success=False`.
- Sentiment data is merged left onto price data; missing dates default to `sentiment_score=0`.
- `DataSourceAgent` caches constituents for `cache_ttl_hours` (default 24h); delete `.cache/sp500_constituents.csv` to force refresh.
- Output reports are written to `report/` (gitignored); filenames include industry and date.

## Tests

All tests in `tests/test_stock_picker.py` make **no network calls**. The `make_config()` helper constructs `AnalysisConfig` via `__new__` to bypass `__post_init__` side effects (NLTK downloads, directory creation). New tests should follow the same pattern.
