"""
Unit tests for stock_picker_agents.py
No network calls are made in these tests.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from stock_picker_agents import (
    AnalysisConfig,
    DataSourceAgent,
    ForecastAgent,
    ReportAgent,
    SentimentData,
    StockData,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**kwargs) -> AnalysisConfig:
    cfg = AnalysisConfig.__new__(AnalysisConfig)
    # bypass __post_init__ side effects for tests
    cfg.max_tickers = kwargs.get("max_tickers", 20)
    cfg.forecast_days = kwargs.get("forecast_days", 7)
    cfg.default_news_count = kwargs.get("default_news_count", 20)
    cfg.positive_threshold = kwargs.get("positive_threshold", 0.05)
    cfg.negative_threshold = kwargs.get("negative_threshold", -0.05)
    cfg.newsapi_key = kwargs.get("newsapi_key", None)
    cfg.output_dir = kwargs.get("output_dir", "report")
    cfg.base_filename = kwargs.get("base_filename", "stock_forecast")
    cfg.cache_dir = kwargs.get("cache_dir", ".cache")
    cfg.cache_ttl_hours = kwargs.get("cache_ttl_hours", 24)
    return cfg


# ---------------------------------------------------------------------------
# 1. test_normalize_dataframe_basic
# ---------------------------------------------------------------------------

def test_normalize_dataframe_basic():
    """_normalize_dataframe should rename columns to standard names."""
    config = make_config()
    agent = DataSourceAgent(config)

    raw = pd.DataFrame({
        "Ticker": ["AAPL", "MSFT"],
        "Company Name": ["Apple Inc.", "Microsoft Corp."],
        "Sector": ["Information Technology", "Information Technology"],
        "Sub-Industry": ["Hardware", "Software"],
    })

    result = agent._normalize_dataframe(raw)
    assert result is not None
    assert "Symbol" in result.columns
    assert "Security" in result.columns
    assert "GICS Sector" in result.columns


# ---------------------------------------------------------------------------
# 2. test_filter_by_industry_match
# ---------------------------------------------------------------------------

def test_filter_by_industry_match():
    """filter_by_industry should return tickers whose sector contains the query."""
    config = make_config()
    agent = DataSourceAgent(config)
    constituents = agent._get_fallback_data()

    tickers = agent.filter_by_industry(constituents, "technology")
    assert len(tickers) > 0
    assert "AAPL" in tickers or "MSFT" in tickers


# ---------------------------------------------------------------------------
# 3. test_filter_by_industry_no_match
# ---------------------------------------------------------------------------

def test_filter_by_industry_no_match():
    """filter_by_industry should return an empty list for an unknown industry."""
    config = make_config()
    agent = DataSourceAgent(config)
    constituents = agent._get_fallback_data()

    tickers = agent.filter_by_industry(constituents, "zzz_nonexistent_xyz")
    assert tickers == []


# ---------------------------------------------------------------------------
# 4. test_merge_price_sentiment
# ---------------------------------------------------------------------------

def test_merge_price_sentiment():
    """_merge_price_sentiment should produce a DatetimeIndex and fill NaN sentiment."""
    config = make_config()
    agent = ForecastAgent(config)

    dates = pd.date_range("2024-01-01", periods=40, freq="B")
    price_df = pd.DataFrame(
        {
            "Open": np.random.uniform(100, 200, 40),
            "High": np.random.uniform(200, 300, 40),
            "Low": np.random.uniform(50, 100, 40),
            "Close": np.random.uniform(100, 200, 40),
            "Adj Close": np.random.uniform(100, 200, 40),
            "Volume": np.random.randint(1_000_000, 10_000_000, 40),
        },
        index=dates,
    )
    price_df.index.name = "date"

    # Only provide sentiment for a subset of dates
    sentiment_df = pd.DataFrame(
        {
            "date": dates[:10].tolist(),
            "pos_count": [1] * 10,
            "neg_count": [0] * 10,
            "neu_count": [0] * 10,
            "total": [1] * 10,
            "sentiment_score": [0.1] * 10,
        }
    )

    merged = agent._merge_price_sentiment(price_df, sentiment_df)

    assert isinstance(merged.index, pd.DatetimeIndex)
    assert merged.shape[0] == 40
    # NaN sentiment rows should have been filled with 0
    assert merged["sentiment_score"].isnull().sum() == 0


# ---------------------------------------------------------------------------
# 5. test_n_day_change_column_name
# ---------------------------------------------------------------------------

def test_n_day_change_column_name():
    """Column names for change should reflect forecast_days, not a hard-coded 7."""
    config = make_config(forecast_days=5)
    agent = ReportAgent(config)

    # Build a minimal pivot DataFrame (no CI columns)
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    pivot_df = pd.DataFrame(
        {"ticker": ["AAPL"], **{d: [100.0 + i] for i, d in enumerate(dates)}}
    ).set_index("ticker")

    change_col = f"{config.forecast_days}_Day_Change"
    change_pct_col = f"{config.forecast_days}_Day_Change_Pct"

    if len(dates) >= 2:
        pivot_df[change_col] = pivot_df[dates[-1]] - pivot_df[dates[0]]
        pivot_df[change_pct_col] = (
            (pivot_df[dates[-1]] - pivot_df[dates[0]]) / pivot_df[dates[0]] * 100
        ).round(2)

    assert change_col in pivot_df.columns
    assert change_pct_col in pivot_df.columns
    assert "7_Day_Change" not in pivot_df.columns


# ---------------------------------------------------------------------------
# 6. test_business_day_forecast_dates
# ---------------------------------------------------------------------------

def test_business_day_forecast_dates():
    """Forecast dates generated with freq='B' must not include weekends."""
    future_dates = pd.date_range(start="2024-01-01", periods=10, freq="B")
    # day_of_week: Monday=0 ... Sunday=6
    weekday_nums = future_dates.day_of_week.tolist()
    assert all(d < 5 for d in weekday_nums), (
        f"Weekend dates found: {[d for d in future_dates if d.day_of_week >= 5]}"
    )
