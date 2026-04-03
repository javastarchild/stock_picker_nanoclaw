#!/usr/bin/env python
# coding: utf-8

"""
MCP Stock Analysis Agents
========================
A modular stock analysis system using MCP agent architecture.

Agents:
- DataSourceAgent: Handles S&P 500 constituent data
- StockDataAgent: Fetches and processes stock price data
- NewsAgent: Fetches and processes news articles
- SentimentAgent: Performs sentiment analysis
- ForecastAgent: Creates price forecasts using SARIMAX
- ReportAgent: Generates and saves reports

Usage:
    orchestrator = StockAnalysisOrchestrator()
    results = orchestrator.run_analysis("technology", lookback_months=6)
"""

import logging
import os
import sys
import warnings
import datetime as dt
from datetime import date
from typing import List, Tuple, Dict, Optional, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json

import pandas as pd
import yfinance as yf
import requests
from tqdm import tqdm
import numpy as np

# Sentiment
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# Forecasting
import statsmodels.api as sm
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.statespace import sarimax


# =============================================================================
# Configuration and Data Classes
# =============================================================================

@dataclass
class AnalysisConfig:
    """Configuration for stock analysis"""
    max_tickers: int = 20
    forecast_days: int = 7
    default_news_count: int = 20
    positive_threshold: float = 0.05
    negative_threshold: float = -0.05
    newsapi_key: Optional[str] = None
    output_dir: str = "report"
    base_filename: str = "stock_forecast"
    cache_dir: str = ".cache"
    cache_ttl_hours: int = 24

    def __post_init__(self):
        if self.newsapi_key is None:
            self.newsapi_key = os.getenv("NEWSAPI_KEY")
        if not self.newsapi_key:
            logging.getLogger("AnalysisConfig").warning(
                "NEWSAPI_KEY not set. News analysis will be skipped."
            )

@dataclass
class StockData:
    """Container for stock price data"""
    ticker: str
    data: pd.DataFrame
    start_date: dt.date
    end_date: dt.date

@dataclass
class NewsData:
    """Container for news articles"""
    query: str
    articles: pd.DataFrame
    fetch_date: dt.date

@dataclass
class SentimentData:
    """Container for sentiment analysis results"""
    daily_sentiment: pd.DataFrame
    query: str
    total_articles: int

@dataclass
class ForecastData:
    """Container for forecast results"""
    ticker: str
    forecast: pd.Series
    model_result: Any
    success: bool
    error: Optional[str] = None
    conf_int: Optional[pd.DataFrame] = None

# =============================================================================
# Base Agent Class
# =============================================================================

class BaseAgent(ABC):
    """Base class for all MCP agents"""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.name = self.__class__.__name__
        self.logger = logging.getLogger(self.name)

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """Execute the agent's main function"""
        pass

# =============================================================================
# Data Source Agent
# =============================================================================

class DataSourceAgent(BaseAgent):
    """Agent responsible for obtaining S&P 500 constituent data"""
    
    def execute(self) -> pd.DataFrame:
        """Get S&P 500 constituents with multiple fallback sources"""
        self.logger.info("Starting S&P 500 constituent data collection")

        # --- Cache check ---
        cache_path = os.path.join(self.config.cache_dir, "sp500_constituents.csv")
        if os.path.exists(cache_path):
            age_hours = (dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(cache_path))).total_seconds() / 3600
            if age_hours < self.config.cache_ttl_hours:
                self.logger.info(f"Loading S&P 500 constituents from cache (age {age_hours:.1f}h)")
                return pd.read_csv(cache_path)

        sources = [
            {
                "name": "Wikipedia",
                "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                "method": "html"
            },
            {
                "name": "GitHub CSV (datasets)",
                "url": "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
                "method": "csv"
            },
            {
                "name": "GitHub CSV (alternative)",
                "url": "https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes(03-01-2023).csv",
                "method": "csv"
            }
        ]

        for source in sources:
            try:
                self.logger.info(f"Trying {source['name']}...")
                df = self._fetch_from_source(source)
                if df is not None:
                    self.logger.info(f"Successfully loaded {len(df)} tickers from {source['name']}")
                    os.makedirs(self.config.cache_dir, exist_ok=True)
                    df.to_csv(cache_path, index=False)
                    return df
            except Exception as e:
                self.logger.warning(f"{source['name']} failed: {e}")
                continue

        # Final fallback
        self.logger.warning("All external sources failed, using built-in fallback data")
        return self._get_fallback_data()
    
    def _fetch_from_source(self, source: dict) -> Optional[pd.DataFrame]:
        """Fetch data from a specific source"""
        if source["method"] == "html":
            tables = pd.read_html(source["url"], header=0)
            if not tables:
                return None
            df = tables[0].copy()
        else:  # CSV
            df = pd.read_csv(source["url"])
        
        if df.empty:
            return None
        
        return self._normalize_dataframe(df)
    
    def _normalize_dataframe(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Normalize column names and data structure"""
        # Clean up unicode characters in column names
        df.columns = (
            df.columns.astype(str)
                     .str.replace("–", "-", regex=False)
                     .str.replace("‑", "-", regex=False)  
                     .str.replace("\u2011", "-", regex=False)
                     .str.strip()
        )
        
        # Smart column mapping
        rename_map = {}
        found_columns = {"Symbol": False, "Security": False, "GICS Sector": False, "GICS Sub‑Industry": False}
        
        for col in df.columns:
            col_lower = col.lower()
            
            if not found_columns["Symbol"] and any(x in col_lower for x in ["symbol", "ticker"]):
                rename_map[col] = "Symbol"
                found_columns["Symbol"] = True
            elif not found_columns["Security"] and any(x in col_lower for x in ["security", "company", "name"]) and "sub" not in col_lower:
                rename_map[col] = "Security"
                found_columns["Security"] = True
            elif not found_columns["GICS Sector"] and "sector" in col_lower and "sub" not in col_lower:
                rename_map[col] = "GICS Sector"
                found_columns["GICS Sector"] = True
            elif not found_columns["GICS Sub‑Industry"] and (
                ("sub" in col_lower and "industry" in col_lower) or
                "subindustry" in col_lower.replace(" ", "").replace("-", "").replace("_", "")
            ):
                rename_map[col] = "GICS Sub‑Industry"
                found_columns["GICS Sub‑Industry"] = True
        
        df.rename(columns=rename_map, inplace=True)
        
        # Create sub-industry fallback
        if "GICS Sub‑Industry" not in df.columns and "GICS Sector" in df.columns:
            df["GICS Sub‑Industry"] = df["GICS Sector"]
        
        # Check minimum requirements
        required = {"Symbol", "Security", "GICS Sector"}
        if not required.issubset(df.columns):
            return None
        
        # Normalize ticker symbols
        df["Symbol"] = df["Symbol"].astype(str).str.replace(".", "-", regex=False)
        
        # Ensure sub-industry exists
        if "GICS Sub‑Industry" not in df.columns:
            df["GICS Sub‑Industry"] = "Unknown"
        
        return df.dropna(subset=["Symbol"]).reset_index(drop=True)
    
    def _get_fallback_data(self) -> pd.DataFrame:
        """Return fallback dataset with major stocks"""
        fallback_data = [
            # Technology
            ("AAPL", "Apple Inc.", "Information Technology", "Technology Hardware, Storage & Peripherals"),
            ("MSFT", "Microsoft Corporation", "Information Technology", "Systems Software"),
            ("GOOGL", "Alphabet Inc.", "Communication Services", "Interactive Media & Services"),
            ("AMZN", "Amazon.com Inc.", "Consumer Discretionary", "Internet & Direct Marketing Retail"),
            ("NVDA", "NVIDIA Corporation", "Information Technology", "Semiconductors & Semiconductor Equipment"),
            ("META", "Meta Platforms Inc.", "Communication Services", "Interactive Media & Services"),
            ("TSLA", "Tesla Inc.", "Consumer Discretionary", "Automobiles"),
            
            # Finance
            ("JPM", "JPMorgan Chase & Co.", "Financials", "Banks"),
            ("BAC", "Bank of America Corp.", "Financials", "Banks"),
            ("WFC", "Wells Fargo & Company", "Financials", "Banks"),
            ("GS", "Goldman Sachs Group Inc.", "Financials", "Investment Banking & Brokerage"),
            ("MS", "Morgan Stanley", "Financials", "Investment Banking & Brokerage"),
            ("AXP", "American Express Company", "Financials", "Consumer Finance"),
            ("V", "Visa Inc.", "Information Technology", "Data Processing & Outsourced Services"),
            ("MA", "Mastercard Incorporated", "Information Technology", "Data Processing & Outsourced Services"),
            
            # Healthcare
            ("JNJ", "Johnson & Johnson", "Health Care", "Pharmaceuticals"),
            ("PFE", "Pfizer Inc.", "Health Care", "Pharmaceuticals"),
            ("UNH", "UnitedHealth Group Incorporated", "Health Care", "Health Care Plans"),
            ("ABBV", "AbbVie Inc.", "Health Care", "Biotechnology"),
            
            # Industrial  
            ("BA", "Boeing Company", "Industrials", "Aerospace & Defense"),
            ("CAT", "Caterpillar Inc.", "Industrials", "Construction & Farm Machinery & Heavy Trucks"),
            ("GE", "General Electric Company", "Industrials", "Industrial Conglomerates"),
            
            # Consumer
            ("KO", "Coca-Cola Company", "Consumer Staples", "Soft Drinks"),
            ("PEP", "PepsiCo Inc.", "Consumer Staples", "Soft Drinks"),
            ("WMT", "Walmart Inc.", "Consumer Staples", "Hypermarkets & Super Centers"),
            ("HD", "Home Depot Inc.", "Consumer Discretionary", "Home Improvement Retail"),
            ("MCD", "McDonald's Corporation", "Consumer Discretionary", "Restaurants"),
        ]
        
        return pd.DataFrame(fallback_data, columns=["Symbol", "Security", "GICS Sector", "GICS Sub‑Industry"])

    def filter_by_industry(self, constituents: pd.DataFrame, industry: str) -> List[str]:
        """Filter tickers by industry string"""
        industry = industry.lower().strip()
        if not industry:
            raise ValueError("Industry string must not be empty")

        # Find relevant columns
        sector_col = next((c for c in constituents.columns if "sector" in c.lower()), None)
        subind_col = next((c for c in constituents.columns if "sub" in c.lower() and "industry" in c.lower()), None)

        if sector_col is None and subind_col is None:
            raise KeyError(f"No sector or sub-industry column found. Available: {list(constituents.columns)}")

        # Build search mask
        mask = pd.Series(False, index=constituents.index)

        if sector_col:
            mask |= constituents[sector_col].fillna("").astype(str).str.lower().str.contains(industry, na=False)

        if subind_col:
            mask |= constituents[subind_col].fillna("").astype(str).str.lower().str.contains(industry, na=False)

        tickers = constituents.loc[mask, "Symbol"].tolist()

        # Fallback: search company names
        if not tickers:
            name_col = next((c for c in constituents.columns if c.lower() in {"security", "name"}), None)
            if name_col:
                mask_name = constituents[name_col].fillna("").astype(str).str.lower().str.contains(industry, na=False)
                tickers = constituents.loc[mask_name, "Symbol"].tolist()

        return tickers

# =============================================================================
# Stock Data Agent
# =============================================================================

class StockDataAgent(BaseAgent):
    """Agent responsible for fetching stock price data"""
    
    def execute(self, ticker: str, start_date: dt.date, end_date: dt.date) -> Optional[StockData]:
        """Fetch stock data for a single ticker"""
        try:
            raw = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=False)
            
            if raw.empty:
                return None
            
            # Handle MultiIndex columns
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            
            # Keep only needed columns
            price_cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
            available_cols = [col for col in price_cols if col in raw.columns]
            raw = raw[available_cols]
            
            # Ensure proper datetime index
            raw.index = pd.to_datetime(raw.index)
            raw.index.name = "date"
            
            return StockData(
                ticker=ticker,
                data=raw,
                start_date=start_date,
                end_date=end_date
            )
            
        except Exception as e:
            self.logger.error(f"Failed to fetch data for {ticker}: {e}")
            return None

    def execute_batch(self, tickers: List[str], start_date: dt.date, end_date: dt.date) -> Dict[str, Optional["StockData"]]:
        """Batch-download OHLCV data for multiple tickers in a single API call."""
        result: Dict[str, Optional[StockData]] = {}
        if not tickers:
            return result
        try:
            raw = yf.download(
                tickers, start=start_date, end=end_date,
                group_by="ticker", auto_adjust=False, progress=False,
                threads=True
            )
            if raw.empty:
                self.logger.warning("Batch download returned empty DataFrame")
                return {t: None for t in tickers}

            price_cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]

            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        # yfinance returns a flat DataFrame for a single ticker
                        df = raw.copy()
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                    else:
                        df = raw[ticker].copy() if ticker in raw.columns.get_level_values(0) else pd.DataFrame()

                    if df.empty:
                        result[ticker] = None
                        continue

                    available_cols = [c for c in price_cols if c in df.columns]
                    df = df[available_cols]
                    df.index = pd.to_datetime(df.index)
                    df.index.name = "date"

                    result[ticker] = StockData(
                        ticker=ticker,
                        data=df,
                        start_date=start_date,
                        end_date=end_date,
                    )
                except Exception as e:
                    self.logger.warning(f"Could not extract data for {ticker} from batch: {e}")
                    result[ticker] = None
        except Exception as e:
            self.logger.error(f"Batch download failed: {e}. Falling back to per-ticker download.")
            for ticker in tickers:
                result[ticker] = self.execute(ticker, start_date, end_date)

        return result

# =============================================================================
# News Agent
# =============================================================================

class NewsAgent(BaseAgent):
    """Agent responsible for fetching news articles"""
    
    def execute(self, query: str, n_articles: int = None) -> NewsData:
        """Fetch news articles for the given query"""
        if n_articles is None:
            n_articles = self.config.default_news_count
            
        if not self.config.newsapi_key:
            self.logger.warning("No NewsAPI key available, returning empty news data")
            return NewsData(
                query=query,
                articles=pd.DataFrame(),
                fetch_date=dt.date.today()
            )
        
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "language": "en", 
                "pageSize": n_articles,
                "sortBy": "publishedAt",
                "apiKey": self.config.newsapi_key,
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                raise RuntimeError(f"NewsAPI request failed: {response.status_code}")
            
            raw = response.json()
            articles = raw.get("articles", [])
            
            if not articles:
                self.logger.warning(f"No news articles found for query '{query}'")
                return NewsData(query=query, articles=pd.DataFrame(), fetch_date=dt.date.today())

            df = pd.DataFrame(articles)
            df = df[["publishedAt", "title", "description", "content", "url"]].copy()
            df["publishedAt"] = pd.to_datetime(df["publishedAt"]).dt.date
            df["content"] = df["content"].fillna(df["title"]).fillna(df["description"])

            self.logger.info(f"Fetched {len(df)} articles for '{query}'")
            
            return NewsData(
                query=query,
                articles=df,
                fetch_date=dt.date.today()
            )
            
        except Exception as e:
            self.logger.error(f"Failed to fetch news for '{query}': {e}")
            return NewsData(query=query, articles=pd.DataFrame(), fetch_date=dt.date.today())

# =============================================================================
# Sentiment Agent
# =============================================================================

class SentimentAgent(BaseAgent):
    """Agent responsible for sentiment analysis"""
    
    def __init__(self, config: AnalysisConfig):
        super().__init__(config)
        try:
            self.sia = SentimentIntensityAnalyzer()
        except LookupError:
            self.logger.warning("VADER lexicon not found. Attempting to download...")
            import nltk
            nltk.download('vader_lexicon', quiet=True)
            self.sia = SentimentIntensityAnalyzer()
    
    def execute(self, news_data: NewsData) -> SentimentData:
        """Perform sentiment analysis on news articles"""
        if news_data.articles.empty:
            self.logger.info("No articles to analyze, returning neutral sentiment")
            return SentimentData(
                daily_sentiment=pd.DataFrame(columns=["date", "pos_count", "neg_count", "neu_count", "total", "sentiment_score"]),
                query=news_data.query,
                total_articles=0
            )
        
        scores = []
        for _, row in news_data.articles.iterrows():
            text = str(row["content"])
            compound = self.sia.polarity_scores(text)["compound"]
            
            if compound >= self.config.positive_threshold:
                label = "positive"
            elif compound <= self.config.negative_threshold:
                label = "negative"
            else:
                label = "neutral"
            
            scores.append({
                "date": row["publishedAt"],
                "compound": compound,
                "sentiment": label
            })
        
        df_sent = pd.DataFrame(scores)
        
        # Aggregate to daily sentiment
        daily = df_sent.groupby("date").agg(
            avg_compound=("compound", "mean"),
            pos_count=("sentiment", lambda x: (x == "positive").sum()),
            neg_count=("sentiment", lambda x: (x == "negative").sum()),
            neu_count=("sentiment", lambda x: (x == "neutral").sum()),
            total=("sentiment", "count")
        )
        
        daily["sentiment_score"] = daily["avg_compound"]
        daily = daily.drop(columns=["avg_compound"]).reset_index()
        
        self.logger.info(f"Analyzed {len(df_sent)} articles across {len(daily)} unique dates")
        
        return SentimentData(
            daily_sentiment=daily,
            query=news_data.query,
            total_articles=len(df_sent)
        )

# =============================================================================
# Forecast Agent
# =============================================================================

class ForecastAgent(BaseAgent):
    """Agent responsible for creating price forecasts"""
    
    def execute(self, stock_data: StockData, sentiment_data: SentimentData) -> ForecastData:
        """Create forecast for a single stock"""
        try:
            # Merge price and sentiment data
            merged_df = self._merge_price_sentiment(stock_data.data, sentiment_data.daily_sentiment)
            
            if merged_df["sentiment_score"].isnull().all():
                merged_df["sentiment_score"] = 0.0
            
            if len(merged_df) < 30:
                raise ValueError("Not enough observations for SARIMAX (need ≥30 days)")
            
            # Prepare data for modeling
            if not isinstance(merged_df.index, pd.DatetimeIndex):
                merged_df.index = pd.to_datetime(merged_df.index)
            
            y = merged_df["Adj Close"]
            exog = merged_df[["sentiment_score"]]
            
            # Fit SARIMAX model (suppress convergence warnings locally)
            model = SARIMAX(y, exog=exog, order=(1, 1, 1),
                            enforce_stationarity=False, enforce_invertibility=False)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = model.fit(disp=False)

            # Create future exogenous variables using rolling mean of last 5 days
            last_sentiment = exog["sentiment_score"].tail(min(5, len(exog))).mean()
            future_dates = pd.date_range(
                start=merged_df.index[-1] + dt.timedelta(days=1),
                periods=self.config.forecast_days,
                freq="B"
            )
            future_exog = pd.DataFrame(
                {"sentiment_score": np.full(self.config.forecast_days, last_sentiment)},
                index=future_dates
            )

            # Generate forecast with confidence intervals
            forecast_res = result.get_forecast(steps=self.config.forecast_days, exog=future_exog)
            forecast_series = forecast_res.predicted_mean
            conf_int = forecast_res.conf_int()

            # Handle index issues
            if not isinstance(forecast_series.index, pd.DatetimeIndex):
                forecast_series.index = future_dates
                conf_int.index = future_dates

            if hasattr(forecast_series.index, 'date'):
                forecast_series.index = forecast_series.index.date
                conf_int.index = conf_int.index.date
            else:
                forecast_series.index = pd.to_datetime(forecast_series.index).date
                conf_int.index = pd.to_datetime(conf_int.index).date

            return ForecastData(
                ticker=stock_data.ticker,
                forecast=forecast_series,
                model_result=result,
                success=True,
                conf_int=conf_int,
            )
            
        except Exception as e:
            self.logger.error(f"Forecast failed for {stock_data.ticker}: {e}")
            return ForecastData(
                ticker=stock_data.ticker,
                forecast=pd.Series(),
                model_result=None,
                success=False,
                error=str(e)
            )
    
    def _merge_price_sentiment(self, price_df: pd.DataFrame, sentiment_df: pd.DataFrame) -> pd.DataFrame:
        """Merge price and sentiment data"""
        price = price_df.copy()
        
        # Handle MultiIndex columns
        if isinstance(price.columns, pd.MultiIndex):
            price.columns = price.columns.get_level_values(0)
        
        # Ensure date column
        if price.index.name == "date" and isinstance(price.index, pd.DatetimeIndex):
            price = price.reset_index()
        elif price.index.name is None or not isinstance(price.index, pd.DatetimeIndex):
            price = price.reset_index()
            if "date" not in price.columns:
                price = price.rename(columns={price.columns[0]: "date"})
        
        price["date"] = pd.to_datetime(price["date"])
        
        # Prepare sentiment data
        sentiment = sentiment_df.copy()
        if "date" not in sentiment.columns:
            if sentiment.index.name == "date" and isinstance(sentiment.index, pd.DatetimeIndex):
                sentiment = sentiment.reset_index()
            else:
                raise KeyError("Sentiment DataFrame must contain a 'date' column")
        
        sentiment["date"] = pd.to_datetime(sentiment["date"])
        
        # Merge
        merged = pd.merge(price, sentiment, how="left", on="date", suffixes=("", "_sent"))
        
        # Fill missing sentiment values
        sentiment_cols = ["pos_count", "neg_count", "neu_count", "total", "sentiment_score"]
        for col in sentiment_cols:
            if col in merged.columns:
                merged[col] = merged[col].fillna(0)
        
        merged.set_index("date", inplace=True)
        
        if not isinstance(merged.index, pd.DatetimeIndex):
            raise TypeError("After merging, index is not DatetimeIndex")
        
        return merged

# =============================================================================
# Report Agent
# =============================================================================

class ReportAgent(BaseAgent):
    """Agent responsible for generating reports"""
    
    def execute(self, forecast_results: List[ForecastData], industry: str) -> str:
        """Generate and save analysis report"""
        # Filter successful forecasts
        successful_forecasts = [f for f in forecast_results if f.success]

        if not successful_forecasts:
            self.logger.warning("No successful forecasts to report")
            return ""

        # Create results DataFrame
        all_forecasts = []
        for forecast_data in successful_forecasts:
            df = forecast_data.forecast.reset_index()
            df.columns = ["date", "pred_adj_close"]
            df["ticker"] = forecast_data.ticker
            # Attach confidence interval columns if available
            if forecast_data.conf_int is not None:
                ci = forecast_data.conf_int.reset_index(drop=True)
                df["ci_lower"] = ci.iloc[:, 0].values
                df["ci_upper"] = ci.iloc[:, 1].values
            else:
                df["ci_lower"] = None
                df["ci_upper"] = None
            all_forecasts.append(df[["ticker", "date", "pred_adj_close", "ci_lower", "ci_upper"]])

        final_df = pd.concat(all_forecasts, ignore_index=True)
        final_df.sort_values(["ticker", "date"], inplace=True)

        # Save to file
        filepath = self._save_to_file(final_df, industry)

        # Display results
        self._display_results(final_df, forecast_results)

        return filepath
    
    def _save_to_file(self, results_df: pd.DataFrame, industry: str) -> str:
        """Save results to CSV file with pivot format"""
        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)
        
        # Generate filename
        current_date = dt.date.today().strftime("%Y%m%d")
        clean_industry = "".join(c for c in industry if c.isalnum() or c in (' ', '-', '_')).rstrip()
        clean_industry = clean_industry.replace(' ', '_').lower()
        
        filename = f"{self.config.base_filename}_{clean_industry}_{current_date}.csv"
        filepath = os.path.join(self.config.output_dir, filename)
        
        # Pivot point forecasts: one row per ticker, columns for each date
        pivot_df = results_df.pivot(index='ticker', columns='date', values='pred_adj_close')
        pivot_df = pivot_df.reindex(sorted(pivot_df.columns), axis=1)

        # Format date columns
        formatted_dates = []
        for date_col in pivot_df.columns:
            if hasattr(date_col, 'strftime'):
                formatted_dates.append(date_col.strftime('%Y-%m-%d'))
            else:
                try:
                    parsed_date = pd.to_datetime(date_col).strftime('%Y-%m-%d')
                    formatted_dates.append(parsed_date)
                except Exception:
                    formatted_dates.append(str(date_col))

        pivot_df.columns = formatted_dates

        # Add CI columns ({date}_lower / {date}_upper) per date
        if "ci_lower" in results_df.columns and "ci_upper" in results_df.columns:
            ci_lower_pivot = results_df.pivot(index='ticker', columns='date', values='ci_lower')
            ci_upper_pivot = results_df.pivot(index='ticker', columns='date', values='ci_upper')
            ci_lower_pivot = ci_lower_pivot.reindex(sorted(ci_lower_pivot.columns), axis=1)
            ci_upper_pivot = ci_upper_pivot.reindex(sorted(ci_upper_pivot.columns), axis=1)
            for i, date_col in enumerate(formatted_dates):
                orig_col = list(ci_lower_pivot.columns)[i]
                pivot_df[f"{date_col}_lower"] = ci_lower_pivot[orig_col]
                pivot_df[f"{date_col}_upper"] = ci_upper_pivot[orig_col]

        # Calculate changes using forecast_days-aware column names
        change_col = f'{self.config.forecast_days}_Day_Change'
        change_pct_col = f'{self.config.forecast_days}_Day_Change_Pct'
        if len(formatted_dates) >= 2:
            pivot_df[change_col] = pivot_df[formatted_dates[-1]] - pivot_df[formatted_dates[0]]
            pivot_df[change_pct_col] = (
                (pivot_df[formatted_dates[-1]] - pivot_df[formatted_dates[0]])
                / pivot_df[formatted_dates[0]] * 100
            ).round(2)
        else:
            pivot_df[change_col] = 0
            pivot_df[change_pct_col] = 0

        # Round numeric columns
        numeric_cols = pivot_df.select_dtypes(include=[np.number]).columns
        pivot_df[numeric_cols] = pivot_df[numeric_cols].round(2)

        pivot_df = pivot_df.reset_index()
        pivot_df.to_csv(filepath, index=False)

        # Create summary report
        self._create_summary_report(pivot_df, industry, filename, formatted_dates)

        self.logger.info(f"Results saved to: {filepath}")
        return filepath
    
    def _create_summary_report(self, pivot_df: pd.DataFrame, industry: str, filename: str, date_columns: List[str]):
        """Create text summary report"""
        current_date = dt.date.today().strftime("%Y%m%d")
        clean_industry = industry.replace(' ', '_').lower()
        summary_filename = f"{self.config.base_filename}_{clean_industry}_{current_date}_summary.txt"
        summary_filepath = os.path.join(self.config.output_dir, summary_filename)
        
        with open(summary_filepath, 'w') as f:
            f.write("Stock Forecast Analysis Report\n")
            f.write("=" * 40 + "\n\n")
            f.write(f"Analysis Date: {dt.date.today().strftime('%Y-%m-%d')}\n")
            f.write(f"Industry: {industry}\n")
            f.write(f"Total Tickers Analyzed: {pivot_df.shape[0]}\n")
            f.write(f"Forecast Period: {self.config.forecast_days} days\n\n")
            
            f.write("Tickers in Analysis:\n")
            for ticker in sorted(pivot_df['ticker']):
                f.write(f"  - {ticker}\n")
            
            f.write(f"\nData Format:\n")
            f.write(f"  - One row per ticker\n")
            f.write(f"  - Date columns: {', '.join(date_columns)}\n")
            change_col = f'{self.config.forecast_days}_Day_Change'
            change_pct_col = f'{self.config.forecast_days}_Day_Change_Pct'
            f.write(f"  - {change_col}: Absolute dollar change from first to last day\n")
            f.write(f"  - {change_pct_col}: Percentage change from first to last day\n\n")

            # Statistics
            if not pivot_df.empty and change_pct_col in pivot_df.columns:
                avg_change = pivot_df[change_pct_col].mean()
                max_gainer = pivot_df.loc[pivot_df[change_pct_col].idxmax()]
                max_loser = pivot_df.loc[pivot_df[change_pct_col].idxmin()]

                f.write("Forecast Summary:\n")
                f.write(f"  - Average {self.config.forecast_days}-day change: {avg_change:.2f}%\n")
                f.write(f"  - Best performer: {max_gainer['ticker']} ({max_gainer[change_pct_col]:.2f}%)\n")
                f.write(f"  - Worst performer: {max_loser['ticker']} ({max_loser[change_pct_col]:.2f}%)\n\n")
            
            f.write(f"Files Generated:\n")
            f.write(f"  - Data: {filename}\n")
            f.write(f"  - Summary: {summary_filename}\n")
    
    def _display_results(self, final_df: pd.DataFrame, forecast_results: List[ForecastData]):
        """Display results to console"""
        with pd.option_context('display.max_rows', None):
            print(f"\n🔮  {self.config.forecast_days}‑day predicted adjusted close prices:\n")
            print(final_df.to_string(index=False))
        
        # Show failed tickers
        failed_forecasts = [f for f in forecast_results if not f.success]
        if failed_forecasts:
            print("\n⚠️  The following tickers could not be processed:")
            failed_tickers = [f.ticker for f in failed_forecasts]
            print(", ".join(failed_tickers))

# =============================================================================
# Orchestrator
# =============================================================================

class StockAnalysisOrchestrator:
    """Main orchestrator that coordinates all agents"""
    
    def __init__(self, config: AnalysisConfig = None):
        if config is None:
            config = AnalysisConfig()
        self.config = config
        self.logger = logging.getLogger("Orchestrator")

        # Initialize agents
        self.data_source_agent = DataSourceAgent(config)
        self.stock_data_agent = StockDataAgent(config)
        self.news_agent = NewsAgent(config)
        self.sentiment_agent = SentimentAgent(config)
        self.forecast_agent = ForecastAgent(config)
        self.report_agent = ReportAgent(config)

        self.logger.info("Stock Analysis Orchestrator initialized")
    
    def run_analysis(self, industry: str, lookback_months: int, news_count: int = None) -> Dict[str, Any]:
        """Run the complete stock analysis workflow"""
        self.logger.info(f"Starting analysis for industry: {industry}")

        # Step 1: Get S&P 500 constituents
        self.logger.info("Step 1: Getting S&P 500 constituents")
        constituents = self.data_source_agent.execute()

        # Step 2: Filter tickers by industry
        self.logger.info("Step 2: Filtering tickers by industry")
        tickers = self.data_source_agent.filter_by_industry(constituents, industry)

        if not tickers:
            self.logger.error(f"No tickers found for industry '{industry}'")
            return {"success": False, "error": "No tickers found", "results": None}

        # Limit tickers
        if len(tickers) > self.config.max_tickers:
            self.logger.info(f"Found {len(tickers)} tickers, limiting to {self.config.max_tickers}")
            tickers = tickers[:self.config.max_tickers]

        self.logger.info(f"Processing {len(tickers)} tickers: {', '.join(tickers)}")

        # Step 3: Calculate date range using calendar-accurate DateOffset
        today = dt.date.today()
        end_date = today
        start_date = (pd.Timestamp(today) - pd.DateOffset(months=lookback_months)).date()
        self.logger.info(f"Date range: {start_date} to {end_date}")

        # Step 4: Fetch news and analyze sentiment
        self.logger.info("Step 4: Fetching news and analyzing sentiment")
        news_data = self.news_agent.execute(industry, news_count)
        sentiment_data = self.sentiment_agent.execute(news_data)

        if sentiment_data.total_articles > 0:
            self.logger.info(
                f"Analyzed {sentiment_data.total_articles} articles across "
                f"{len(sentiment_data.daily_sentiment)} unique dates"
            )
        else:
            self.logger.info("No news articles found, proceeding with neutral sentiment")

        # Step 5: Batch-download price data, then forecast per ticker
        self.logger.info("Step 5: Batch-downloading stock data and forecasting")
        stock_data_map = self.stock_data_agent.execute_batch(tickers, start_date, end_date)

        forecast_results = []
        for ticker in tqdm(tickers, desc="Forecasting tickers"):
            stock_data = stock_data_map.get(ticker)
            if stock_data is None:
                forecast_results.append(ForecastData(
                    ticker=ticker,
                    forecast=pd.Series(),
                    model_result=None,
                    success=False,
                    error="Could not fetch stock data"
                ))
                continue
            forecast_data = self.forecast_agent.execute(stock_data, sentiment_data)
            forecast_results.append(forecast_data)

        # Step 6: Generate report
        self.logger.info("Step 6: Generating report")
        report_path = self.report_agent.execute(forecast_results, industry)

        # Compile results
        successful_count = sum(1 for f in forecast_results if f.success)
        failed_count = len(forecast_results) - successful_count

        results = {
            "success": True,
            "industry": industry,
            "total_tickers": len(tickers),
            "successful_forecasts": successful_count,
            "failed_forecasts": failed_count,
            "report_path": report_path,
            "forecast_results": forecast_results,
            "sentiment_data": sentiment_data,
            "date_range": {"start": start_date, "end": end_date}
        }

        self.logger.info(f"Analysis complete: {successful_count}/{len(tickers)} tickers processed successfully")
        return results

# =============================================================================
# Interactive CLI Interface
# =============================================================================

class StockAnalysisCLI:
    """Command line interface for the stock analysis system"""
    
    def __init__(self):
        self.orchestrator = StockAnalysisOrchestrator()
    
    def run_interactive(self):
        """Run interactive command line interface"""
        print("=" * 60)
        print("🚀 MCP Stock Analysis System")
        print("=" * 60)
        
        try:
            # Get user inputs
            industry = input("Enter the industry to analyze (e.g. technology, auto, finance): ").strip()
            if not industry:
                print("❌ Industry cannot be empty")
                return
            
            months_str = input("Enter look‑back period in months (e.g. 6 for previous 6 months): ").strip()
            try:
                lookback_months = int(months_str)
                if lookback_months <= 0:
                    raise ValueError
            except ValueError:
                print("❌ Invalid number of months. Please enter a positive integer.")
                return
            
            news_count_str = input(f"How many recent news articles to fetch? (default {self.orchestrator.config.default_news_count}): ").strip()
            if news_count_str:
                try:
                    news_count = int(news_count_str)
                except ValueError:
                    print("❌ Invalid news count – using default.")
                    news_count = None
            else:
                news_count = None
            
            # Run analysis
            results = self.orchestrator.run_analysis(industry, lookback_months, news_count)
            
            if results["success"]:
                print("\n✅ Analysis completed successfully!")
                if results["report_path"]:
                    print(f"📄 Report saved to: {results['report_path']}")
                print(f"📊 Summary: {results['successful_forecasts']}/{results['total_tickers']} tickers processed")
            else:
                print(f"\n❌ Analysis failed: {results.get('error', 'Unknown error')}")
            
        except KeyboardInterrupt:
            print("\n\n👋 Analysis cancelled by user")
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
    
    def run_batch(self, industry: str, lookback_months: int, news_count: int = None) -> Dict[str, Any]:
        """Run analysis in batch mode (programmatic)"""
        return self.orchestrator.run_analysis(industry, lookback_months, news_count)

# =============================================================================
# Factory Functions
# =============================================================================

def create_custom_config(**kwargs) -> AnalysisConfig:
    """Create a custom configuration"""
    return AnalysisConfig(**kwargs)

def create_orchestrator(config: AnalysisConfig = None) -> StockAnalysisOrchestrator:
    """Create orchestrator with optional custom config"""
    return StockAnalysisOrchestrator(config)

# =============================================================================
# Main Execution
# =============================================================================

def main():
    """Main function for command line execution"""
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")
    cli = StockAnalysisCLI()
    cli.run_interactive()

# Example usage functions
def example_technology_analysis():
    """Example: Analyze technology stocks"""
    config = create_custom_config(max_tickers=10, forecast_days=5)
    orchestrator = create_orchestrator(config)
    return orchestrator.run_analysis("technology", lookback_months=6, news_count=15)

def example_finance_analysis():
    """Example: Analyze financial stocks"""
    config = create_custom_config(max_tickers=15, forecast_days=7)
    orchestrator = create_orchestrator(config)
    return orchestrator.run_analysis("finance", lookback_months=3, news_count=25)

if __name__ == "__main__":
    main()

# =============================================================================
# Testing and Development
# =============================================================================

def test_individual_agents():
    """Test individual agents in isolation"""
    config = AnalysisConfig()
    
    # Test DataSourceAgent
    print("Testing DataSourceAgent...")
    data_agent = DataSourceAgent(config)
    constituents = data_agent.execute()
    tech_tickers = data_agent.filter_by_industry(constituents, "technology")
    print(f"Found {len(tech_tickers)} tech tickers: {tech_tickers[:5]}...")
    
    # Test StockDataAgent
    print("\nTesting StockDataAgent...")
    stock_agent = StockDataAgent(config)
    if tech_tickers:
        stock_data = stock_agent.execute(tech_tickers[0], 
                                       dt.date.today() - dt.timedelta(days=90), 
                                       dt.date.today())
        if stock_data:
            print(f"Got {len(stock_data.data)} days of data for {stock_data.ticker}")
    
    # Test NewsAgent (only if API key available)
    if config.newsapi_key:
        print("\nTesting NewsAgent...")
        news_agent = NewsAgent(config)
        news_data = news_agent.execute("technology", 5)
        print(f"Got {len(news_data.articles)} articles")
        
        # Test SentimentAgent
        print("\nTesting SentimentAgent...")
        sentiment_agent = SentimentAgent(config)
        sentiment_data = sentiment_agent.execute(news_data)
        print(f"Analyzed sentiment for {sentiment_data.total_articles} articles")
    
    print("\nAgent testing complete!")

def run_quick_test():
    """Run a quick test with minimal data"""
    config = create_custom_config(max_tickers=2, forecast_days=3, default_news_count=5)
    cli = StockAnalysisCLI()
    cli.orchestrator = create_orchestrator(config)
    
    # Test with technology sector
    results = cli.run_batch("technology", lookback_months=2, news_count=5)
    return results