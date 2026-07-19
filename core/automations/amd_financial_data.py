"""Near-real-time Yahoo Finance analytics for the stock analysis automation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_TICKER = "AMD"
STOCK_START_DATE = "2025-01-01"
CACHE_SECONDS = 180
SUPPORTED_TICKERS = (
    "AMD", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA",
    "AVGO", "TSM", "QCOM", "NFLX", "CRM", "ADBE", "INTU",
)
TIMEFRAME_OPTIONS = (
    ("today", "Today (5-minute)"),
    ("5d", "Last 5 trading days (5-minute)"),
    ("1mo", "Last month (daily)"),
    ("ytd", "Year to date (daily)"),
    ("full", "Since Jan. 1, 2025 (daily)"),
)


@dataclass(frozen=True)
class StockAnalyticsResult:
    data: pd.DataFrame
    row_count: int
    chart_data_uri: str
    ticker: str
    timeframe: str
    timeframe_label: str
    start_date: str
    end_date: str
    last_updated: str
    latest_bar: str
    market_status: str
    cards: tuple[dict, ...]
    cache_seconds: int = CACHE_SECONDS


def normalize_ticker(ticker: str | None) -> str:
    normalized = (ticker or DEFAULT_TICKER).strip().upper()
    if normalized not in SUPPORTED_TICKERS:
        raise ValueError(
            f"Unsupported ticker '{normalized}'. Choose one of: "
            + ", ".join(SUPPORTED_TICKERS)
        )
    return normalized


def normalize_timeframe(timeframe: str | None) -> str:
    allowed = {value for value, _ in TIMEFRAME_OPTIONS}
    normalized = (timeframe or "full").strip().lower()
    return normalized if normalized in allowed else "full"


def _timeframe_label(timeframe: str) -> str:
    return dict(TIMEFRAME_OPTIONS)[timeframe]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    expected = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    first = {str(value) for value in df.columns.get_level_values(0)}
    last = {str(value) for value in df.columns.get_level_values(-1)}
    if expected & first:
        df.columns = [str(column[0]) for column in df.columns.to_flat_index()]
    elif expected & last:
        df.columns = [str(column[-1]) for column in df.columns.to_flat_index()]
    else:
        df.columns = [" ".join(str(part) for part in column if part).strip() for column in df.columns.to_flat_index()]
    return df


def _download_price_data(yf, ticker: str, timeframe: str) -> pd.DataFrame:
    if timeframe in {"today", "5d"}:
        df = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=False, prepost=False)
    else:
        today = date.today()
        if timeframe == "1mo":
            start = today - timedelta(days=45)
        elif timeframe == "ytd":
            start = date(today.year, 1, 1)
        else:
            start = date.fromisoformat(STOCK_START_DATE)
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
    if df is None:
        return pd.DataFrame()
    df = _normalize_columns(df.copy()).sort_index()
    if timeframe == "today" and not df.empty:
        eastern = ZoneInfo("America/New_York")
        idx = pd.to_datetime(df.index)
        if idx.tz is None:
            idx = idx.tz_localize(eastern)
        else:
            idx = idx.tz_convert(eastern)
        df.index = idx
        latest_session = idx.date.max()
        df = df[idx.date == latest_session]
    return df


def _price_column(df: pd.DataFrame) -> str:
    return "Adj Close" if "Adj Close" in df.columns else "Close"


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def _add_indicators(df: pd.DataFrame, intraday: bool) -> pd.DataFrame:
    if df.empty:
        return df
    price = _price_column(df)
    out = df.copy()
    out["simple_rtn"] = out[price].pct_change()
    out["EMA_20"] = out[price].ewm(span=20, adjust=False).mean()
    out["EMA_50"] = out[price].ewm(span=50, adjust=False).mean()
    out["RSI_14"] = _rsi(out[price])
    out["MACD"] = out[price].ewm(span=12, adjust=False).mean() - out[price].ewm(span=26, adjust=False).mean()
    out["MACD_signal"] = out["MACD"].ewm(span=9, adjust=False).mean()
    out["MACD_hist"] = out["MACD"] - out["MACD_signal"]
    out["ADX_14"] = _adx(out)
    tr = pd.concat([
        out["High"] - out["Low"],
        (out["High"] - out["Close"].shift()).abs(),
        (out["Low"] - out["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    out["ATR_14"] = tr.rolling(14, min_periods=3).mean()
    out["ATR_pct"] = out["ATR_14"] / out[price] * 100
    annualizer = np.sqrt(78 * 252) if intraday else np.sqrt(252)
    out["Realized_vol"] = out["simple_rtn"].rolling(20, min_periods=5).std() * annualizer * 100
    out["Relative_volume"] = out["Volume"] / out["Volume"].rolling(20, min_periods=3).mean()
    direction = np.sign(out[price].diff()).fillna(0)
    out["OBV"] = (direction * out["Volume"].fillna(0)).cumsum()
    money_flow_multiplier = ((out["Close"] - out["Low"]) - (out["High"] - out["Close"])) / (out["High"] - out["Low"]).replace(0, np.nan)
    money_flow_volume = money_flow_multiplier * out["Volume"]
    out["CMF_20"] = money_flow_volume.rolling(20, min_periods=3).sum() / out["Volume"].rolling(20, min_periods=3).sum()
    return out


def _latest_number(series: pd.Series, default: float = 0.0) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.iloc[-1]) if not clean.empty else default


def _trend_card(df: pd.DataFrame) -> dict:
    price = _price_column(df)
    close = _latest_number(df[price])
    ema20 = _latest_number(df["EMA_20"])
    ema50 = _latest_number(df["EMA_50"])
    adx = _latest_number(df["ADX_14"])
    bullish = close > ema20 > ema50
    bearish = close < ema20 < ema50
    if bullish and adx >= 25:
        label = "Strong bullish"
    elif bearish and adx >= 25:
        label = "Strong bearish"
    elif close > ema20:
        label = "Bullish"
    elif close < ema20:
        label = "Bearish"
    else:
        label = "Neutral"
    return {"title": "Trend", "label": label, "detail": f"ADX {adx:.1f} · Price vs EMA20 {((close / ema20 - 1) * 100) if ema20 else 0:.2f}%"}


def _volatility_card(df: pd.DataFrame) -> dict:
    vol = _latest_number(df["Realized_vol"])
    history = pd.to_numeric(df["Realized_vol"], errors="coerce").dropna()
    percentile = float((history <= vol).mean() * 100) if len(history) else 50.0
    if percentile >= 90:
        label = "Extreme"
    elif percentile >= 70:
        label = "Elevated"
    elif percentile <= 25:
        label = "Low"
    else:
        label = "Normal"
    atr = _latest_number(df["ATR_pct"])
    return {"title": "Volatility", "label": label, "detail": f"Realized vol {vol:.1f}% · ATR {atr:.2f}% · Pctl {percentile:.0f}"}


def _momentum_card(df: pd.DataFrame) -> dict:
    rsi = _latest_number(df["RSI_14"], 50.0)
    hist = pd.to_numeric(df["MACD_hist"], errors="coerce").dropna()
    current = float(hist.iloc[-1]) if len(hist) else 0.0
    previous = float(hist.iloc[-2]) if len(hist) > 1 else current
    if current > 0 and previous <= 0:
        label = "Bullish reversal"
    elif current < 0 and previous >= 0:
        label = "Bearish reversal"
    elif current > previous:
        label = "Strengthening"
    else:
        label = "Weakening"
    return {"title": "Momentum", "label": label, "detail": f"RSI {rsi:.1f} · MACD hist {current:.3f}"}


def _institutional_card(df: pd.DataFrame) -> dict:
    rv = _latest_number(df["Relative_volume"], 1.0)
    cmf = _latest_number(df["CMF_20"])
    obv = pd.to_numeric(df["OBV"], errors="coerce").dropna()
    obv_change = float(obv.iloc[-1] - obv.iloc[max(0, len(obv) - 6)]) if len(obv) else 0.0
    if cmf > 0.05 and obv_change > 0:
        label = "Accumulation"
    elif cmf < -0.05 and obv_change < 0:
        label = "Distribution"
    else:
        label = "Neutral"
    return {"title": "Institutional activity proxy", "label": label, "detail": f"Rel. volume {rv:.2f}× · CMF {cmf:.2f}"}


def _download_market_regime(yf) -> tuple[dict, pd.DataFrame]:
    tickers = ["SPY", "QQQ", "HYG", "TLT", "^VIX"]
    raw = yf.download(tickers, period="6mo", interval="1d", progress=False, auto_adjust=False, group_by="column")
    if raw is None or raw.empty:
        return {"title": "Market regime", "label": "Mixed", "detail": "Benchmark data unavailable"}, pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0)))
        price_field = "Adj Close" if "Adj Close" in level0 else "Close"
        closes = raw[price_field].copy()
    else:
        closes = raw.copy()
    closes = closes.dropna(how="all")
    scores = []
    details = []
    for ticker in ["SPY", "QQQ"]:
        if ticker in closes:
            series = closes[ticker].dropna()
            above = len(series) >= 20 and series.iloc[-1] > series.rolling(20).mean().iloc[-1]
            scores.append(1 if above else 0)
            details.append(f"{ticker} {'↑' if above else '↓'}")
    if "HYG" in closes and "TLT" in closes:
        ratio = (closes["HYG"] / closes["TLT"]).dropna()
        positive = len(ratio) >= 20 and ratio.iloc[-1] > ratio.rolling(20).mean().iloc[-1]
        scores.append(1 if positive else 0)
        details.append(f"Credit {'on' if positive else 'off'}")
    if "^VIX" in closes:
        vix = closes["^VIX"].dropna()
        vix_level = float(vix.iloc[-1]) if len(vix) else 0.0
        calm = vix_level < 25 and (len(vix) < 20 or vix_level <= vix.rolling(20).mean().iloc[-1])
        scores.append(1 if calm else 0)
        details.append(f"VIX {vix_level:.1f}")
    total = sum(scores)
    label = "Risk-on" if total >= 3 else "Risk-off" if total <= 1 else "Mixed"
    return {"title": "Market regime", "label": label, "detail": " · ".join(details)}, closes


def _build_chart_data_uri(df: pd.DataFrame, ticker: str, timeframe_label: str, regime_df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    price = _price_column(df)
    fig, axes = plt.subplots(5, 1, figsize=(13, 16), sharex=False)

    axes[0].plot(df.index, df[price], label=price)
    axes[0].plot(df.index, df["EMA_20"], label="EMA 20")
    axes[0].plot(df.index, df["EMA_50"], label="EMA 50")
    axes[0].set_title(f"{ticker} trend strength — {timeframe_label}")
    axes[0].set_ylabel("Price (USD)")
    axes[0].legend(loc="best")

    axes[1].plot(df.index, df["Realized_vol"], label="Realized volatility")
    axes[1].plot(df.index, df["ATR_pct"], label="ATR %")
    axes[1].set_title("Volatility regime")
    axes[1].set_ylabel("Percent")
    axes[1].legend(loc="best")

    axes[2].plot(df.index, df["RSI_14"], label="RSI 14")
    axes[2].axhline(70, linestyle="--", linewidth=0.8)
    axes[2].axhline(30, linestyle="--", linewidth=0.8)
    axes[2].plot(df.index, df["MACD_hist"], label="MACD histogram")
    axes[2].set_title("Momentum shifts")
    axes[2].legend(loc="best")

    axes[3].plot(df.index, df["OBV"], label="OBV")
    axes[3].plot(df.index, df["CMF_20"], label="CMF 20")
    axes[3].set_title("Institutional activity proxy")
    axes[3].legend(loc="best")

    if not regime_df.empty:
        normalized = regime_df.copy()
        for column in normalized.columns:
            series = normalized[column].dropna()
            if not series.empty:
                normalized[column] = normalized[column] / series.iloc[0] * 100
        for column in ["SPY", "QQQ", "HYG", "TLT"]:
            if column in normalized:
                axes[4].plot(normalized.index, normalized[column], label=column)
        axes[4].set_ylabel("Indexed to 100")
        axes[4].legend(loc="best")
    axes[4].set_title("Risk-on / risk-off benchmark context")

    for axis in axes:
        axis.grid(True, alpha=0.25)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
    plt.tight_layout()
    buffer = BytesIO()
    plt.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return "data:image/png;base64," + base64.b64encode(buffer.read()).decode("ascii")


def _market_status(latest_index) -> str:
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)
    if now.weekday() >= 5:
        return "Market closed — showing latest available session"
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if open_time <= now <= close_time:
        return "Market open — near-real-time 5-minute data available"
    if now < open_time:
        return "Pre-market — regular-session data shown"
    return "Market closed — showing latest available session"


def download_stock_financial_data(
    ticker: str = DEFAULT_TICKER,
    timeframe: str = "full",
    force_refresh: bool = False,
) -> StockAnalyticsResult:
    """Download and score a supported stock using cached Yahoo Finance data."""
    import yfinance as yf
    from django.core.cache import cache

    selected_ticker = normalize_ticker(ticker)
    selected_timeframe = normalize_timeframe(timeframe)
    cache_key = f"stock-analytics-v2:{selected_ticker}:{selected_timeframe}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    intraday = selected_timeframe in {"today", "5d"}
    df = _download_price_data(yf, selected_ticker, selected_timeframe)
    if df.empty:
        raise RuntimeError(f"Yahoo Finance returned no data for {selected_ticker}.")
    df = _add_indicators(df, intraday)
    regime_card, regime_df = _download_market_regime(yf)
    cards = (
        _trend_card(df),
        _volatility_card(df),
        _momentum_card(df),
        _institutional_card(df),
        regime_card,
    )
    label = _timeframe_label(selected_timeframe)
    chart = _build_chart_data_uri(df, selected_ticker, label, regime_df)
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern)
    latest = pd.to_datetime(df.index[-1])
    if latest.tzinfo is None:
        latest = latest.tz_localize(eastern)
    else:
        latest = latest.tz_convert(eastern)

    display_df = df.reset_index()
    result = StockAnalyticsResult(
        data=display_df,
        row_count=len(display_df),
        chart_data_uri=chart,
        ticker=selected_ticker,
        timeframe=selected_timeframe,
        timeframe_label=label,
        start_date=str(pd.to_datetime(df.index[0]).date()),
        end_date=str(pd.to_datetime(df.index[-1]).date()),
        last_updated=now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        latest_bar=latest.strftime("%Y-%m-%d %I:%M %p %Z"),
        market_status=_market_status(df.index[-1]),
        cards=cards,
    )
    cache.set(cache_key, result, CACHE_SECONDS)
    return result


def download_amd_financial_data(
    ticker: str = DEFAULT_TICKER,
    timeframe: str = "full",
    force_refresh: bool = False,
) -> StockAnalyticsResult:
    """Backward-compatible entry point used by the existing Django view."""
    return download_stock_financial_data(ticker, timeframe, force_refresh)

