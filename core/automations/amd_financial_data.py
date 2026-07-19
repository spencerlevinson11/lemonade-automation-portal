"""Yahoo Finance downloader and chart builder for the stock analysis automation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


DEFAULT_TICKER = "AMD"
STOCK_START_DATE = "2025-01-01"
SUPPORTED_TICKERS = (
    "AMD",
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "AVGO",
    "TSM",
    "QCOM",
    "NFLX",
    "CRM",
    "ADBE",
    "INTU",
)


@dataclass(frozen=True)
class StockDownloadResult:
    data: pd.DataFrame
    row_count: int
    chart_data_uri: str
    ticker: str
    start_date: str = STOCK_START_DATE
    end_date: str = ""


def normalize_ticker(ticker: str | None) -> str:
    """Return a supported uppercase ticker, defaulting to AMD."""
    normalized = (ticker or DEFAULT_TICKER).strip().upper()
    if normalized not in SUPPORTED_TICKERS:
        raise ValueError(
            f"Unsupported ticker '{normalized}'. Choose one of: "
            + ", ".join(SUPPORTED_TICKERS)
        )
    return normalized


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return conventional OHLCV column names for a single-ticker download."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df

    expected = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    first_level = {str(value) for value in df.columns.get_level_values(0)}
    last_level = {str(value) for value in df.columns.get_level_values(-1)}

    if expected & first_level:
        df.columns = [str(column[0]) for column in df.columns.to_flat_index()]
    elif expected & last_level:
        df.columns = [str(column[-1]) for column in df.columns.to_flat_index()]
    else:
        df.columns = [
            " ".join(str(part) for part in column if part).strip()
            for column in df.columns.to_flat_index()
        ]
    return df


def _add_simple_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Add daily simple returns using adjusted close when available."""
    price_column = "Adj Close" if "Adj Close" in df.columns else "Close"
    if price_column not in df.columns:
        df["simple_rtn"] = pd.NA
        return df

    df["simple_rtn"] = df[price_column].pct_change()
    return df


def _build_chart_data_uri(df: pd.DataFrame, ticker: str) -> str:
    """Create a two-panel adjusted-price and simple-return chart as a data URI."""
    if df.empty:
        return ""

    price_column = "Adj Close" if "Adj Close" in df.columns else "Close"
    if price_column not in df.columns or "simple_rtn" not in df.columns:
        return ""

    chart_df = df[[price_column, "simple_rtn"]].copy()
    chart_df.index = pd.to_datetime(chart_df.index)

    axes = chart_df.plot(
        subplots=True,
        sharex=True,
        figsize=(12, 7),
        title=[f"{ticker} Adjusted Closing Price", f"{ticker} Daily Simple Return"],
        grid=True,
    )
    axes[0].set_ylabel("Price (USD)")
    axes[1].set_ylabel("Return")
    axes[1].set_xlabel("Date")

    for axis in axes:
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    plt.tight_layout()
    buffer = BytesIO()
    plt.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close("all")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def download_stock_financial_data(ticker: str = DEFAULT_TICKER) -> StockDownloadResult:
    """Download supported stock data from the configured start date through today."""
    import yfinance as yf

    selected_ticker = normalize_ticker(ticker)
    current_date = date.today()
    # yfinance's end date is exclusive, so tomorrow is passed to include today.
    download_end_date = current_date + timedelta(days=1)

    df = yf.download(
        selected_ticker,
        start=STOCK_START_DATE,
        end=download_end_date.isoformat(),
        progress=False,
        auto_adjust=False,
    )

    if df is None:
        df = pd.DataFrame()

    df = _normalize_columns(df.copy())
    df = _add_simple_returns(df)
    chart_data_uri = _build_chart_data_uri(df, selected_ticker)
    display_df = df.reset_index()

    return StockDownloadResult(
        data=display_df,
        row_count=len(display_df),
        chart_data_uri=chart_data_uri,
        ticker=selected_ticker,
        end_date=current_date.isoformat(),
    )


def download_amd_financial_data(ticker: str = DEFAULT_TICKER) -> StockDownloadResult:
    """Backward-compatible entry point used by the existing Django view."""
    return download_stock_financial_data(ticker)

