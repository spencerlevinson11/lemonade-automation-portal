"""Yahoo Finance downloader used by the AMD Financial Data automation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf


AMD_TICKER = "AMD"
AMD_START_DATE = "2025-01-01"
AMD_END_DATE = "2026-07-17"


@dataclass(frozen=True)
class AMDDownloadResult:
    data: pd.DataFrame
    row_count: int
    ticker: str = AMD_TICKER
    start_date: str = AMD_START_DATE
    end_date: str = AMD_END_DATE


def download_amd_financial_data() -> AMDDownloadResult:
    """Download the configured AMD daily market data and normalize it for display."""
    df = yf.download(
        AMD_TICKER,
        start=AMD_START_DATE,
        end=AMD_END_DATE,
        progress=False,
        auto_adjust=False,
    )

    if df is None:
        df = pd.DataFrame()

    # yfinance can return MultiIndex columns even for one ticker. Flatten them so
    # the Django template receives conventional Open/High/Low/Close columns.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(part) for part in column if part).strip()
            for column in df.columns.to_flat_index()
        ]

    df = df.reset_index()
    return AMDDownloadResult(data=df, row_count=len(df))
