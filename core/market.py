from __future__ import annotations
from datetime import datetime, timedelta, date
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter, Retry
import time
from core.config import INDEX_META

ISS_SHARES = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off&iss.only=securities,marketdata&limit=1000"
ISS_INDICES = "https://iss.moex.com/iss/engines/stock/markets/index/securities.json?iss.meta=off&iss.only=securities,marketdata"
ISS_CANDLES = "https://iss.moex.com/iss/engines/stock/markets/{market}/securities/{ticker}/candles.json"
ISS_HISTORY = "https://iss.moex.com/iss/history/engines/stock/markets/{market}/securities/{ticker}.json"
ISS_DIVIDENDS = "https://iss.moex.com/iss/securities/{ticker}/dividends.json?iss.meta=off"

@st.cache_resource(show_spinner=False)
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5)))
    return s

@st.cache_data(ttl=300, show_spinner=False)
def fetch_moex_stocks() -> pd.DataFrame:
    try:
        r = _session().get(ISS_SHARES, timeout=30)
        js = r.json()
        sec = pd.DataFrame(js["securities"]["data"], columns=js["securities"]["columns"])
        mkt = pd.DataFrame(js["marketdata"]["data"], columns=js["marketdata"]["columns"])
    except Exception as e:
        st.warning(f"ISS недоступен: {e}")
        return pd.DataFrame()

    # Защита от отсутствия колонок
    for col in ["LOTSIZE", "MINSTEP", "PREVPRICE", "LISTLEVEL", "ISSUESIZE", "DECIMALS", "SECID", "SHORTNAME"]:
        if col not in sec.columns: sec[col] = 0 if col not in ["SECID", "SHORTNAME"] else ""
    for col in ["LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES", "SECID"]:
        if col not in mkt.columns: mkt[col] = 0 if col != "SECID" else ""

    df = sec[["SECID", "SHORTNAME", "LOTSIZE", "MINSTEP", "PREVPRICE", "LISTLEVEL", "ISSUESIZE", "DECIMALS"]].merge(
        mkt[["SECID", "LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]], on="SECID", how="left")
    
    for c in ["LOTSIZE", "MINSTEP", "PREVPRICE", "LISTLEVEL", "ISSUESIZE", "DECIMALS", "LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        
    df["PRICE"] = df["LAST"].where(df["LAST"] > 0, df["PREVPRICE"])
    df["LOT_VALUE"] = df["PRICE"] * df["LOTSIZE"]
    return df

@st.cache_data(ttl=300, show_spinner=False)
def fetch_moex_indices() -> pd.DataFrame:
    try:
        r = _session().get(ISS_INDICES, timeout=30)
        js = r.json()
        sec = pd.DataFrame(js.get("securities", {}).get("data", []), columns=js.get("securities", {}).get("columns", []))
        mkt = pd.DataFrame(js.get("marketdata", {}).get("data", []), columns=js.get("marketdata", {}).get("columns", []))
    except Exception:
        return pd.DataFrame()

    valid_tickers = ["IMOEX"] + list(INDEX_META.keys())
    if "SECID" not in mkt.columns: mkt["SECID"] = ""
    if "CURRENTVALUE" not in mkt.columns: mkt["CURRENTVALUE"] = 0.0
    if "LASTCHANGEPRCNT" not in mkt.columns: mkt["LASTCHANGEPRCNT"] = 0.0
    if "SECID" not in sec.columns: return pd.DataFrame()

    df = sec[sec["SECID"].isin(valid_tickers)][["SECID", "SHORTNAME"]].merge(
        mkt[["SECID", "CURRENTVALUE", "LASTCHANGEPRCNT"]], on="SECID", how="left")
    
    df["CURRENTVALUE"] = pd.to_numeric(df["CURRENTVALUE"], errors="coerce").fillna(0)
    df["LASTCHANGEPRCNT"] = pd.to_numeric(df["LASTCHANGEPRCNT"], errors="coerce").fillna(0)
    return df

@st.cache_data(ttl=None, show_spinner=False)
def fetch_extreme_close(ticker: str, date_val, market: str = "index") -> tuple[float, str]:
    try:
        if isinstance(date_val, str):
            d = datetime.strptime(date_val, "%d.%m.%Y")
        elif isinstance(date_val, datetime):
            d = date_val
        elif isinstance(date_val, date):
            d = datetime.combine(date_val, datetime.min.time())
        else:
            return 0.0, "-"
    except Exception:
        return 0.0, "-"

    monday = d - timedelta(days=d.isoweekday() - 1)
    friday = monday + timedelta(days=4)
    today = datetime.now()
    if friday > today: friday = today

    frm, till = monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d")
    
    if market == "index":
        url = ISS_HISTORY.format(market="index", ticker=ticker)
    else:
        url = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
    
    try:
        r = _session().get(url, params={"from": frm, "till": till, "iss.meta": "off"}, timeout=10)
        hist = pd.DataFrame(r.json()["history"]["data"], columns=r.json()["history"]["columns"])
        if hist.empty or "CLOSE" not in hist.columns: return 0.0, "-"
        last_row = hist.sort_values("TRADEDATE").iloc[-1]
        return float(last_row["CLOSE"]), str(last_row["TRADEDATE"])
    except Exception:
        return 0.0, "-"

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dividends_moex(ticker: str) -> float:
    """Суммирует дивиденды за последние 12 месяцев, отсекая будущие даты. Нечувствительно к регистру колонок."""
    url = ISS_DIVIDENDS.format(ticker=ticker)
    try:
        r = _session().get(url, timeout=10)
        block = r.json().get("dividends", {})
        cols = block.get("columns", [])
        data = block.get("data", [])
        if not data or not cols: return 0.0

        # Ищем правильные индексы колонок, игнорируя регистр
        date_idx, val_idx = None, None
        for i, c in enumerate(cols):
            c_lower = c.lower()
            if c_lower == "registryclosedate": date_idx = i
            elif c_lower == "value": val_idx = i
            
        if date_idx is None or val_idx is None:
            return 0.0

        today = datetime.now().date()
        one_year_ago = today - timedelta(days=365)
        total_div = 0.0
        
        for row in data:
            reg_date_str = row[date_idx]
            val = row[val_idx]
            if reg_date_str and val:
                try:
                    # Берем только первые 10 символов (YYYY-MM-DD)
                    reg_date = datetime.strptime(str(reg_date_str)[:10], "%Y-%m-%d").date()
                    if one_year_ago <= reg_date <= today:
                        total_div += float(val)
                except Exception:
                    pass
        return total_div
    except Exception:
        return 0.0

@st.cache_data(ttl=180, show_spinner=False)
def fetch_moex_candles(ticker: str, interval: int, days_back: int = 60, market: str = "shares") -> pd.DataFrame:
    frm = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    till = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    url = ISS_CANDLES.format(market=market, ticker=ticker)
    
    chunks, start = [], 0
    for _ in range(30):
        try:
            r = _session().get(url, params={"interval": interval, "from": frm, "till": till, "start": start, "iss.meta": "off"}, timeout=15)
            r.raise_for_status()
            block = r.json().get("candles") or {}
        except Exception:
            break

        data = block.get("data") or []
        if not data: break
        chunks.append(pd.DataFrame(data, columns=block["columns"]))

        if len(data) < 500: break
        start += 500
        time.sleep(0.1)

    if not chunks: return pd.DataFrame()
    df = pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["begin"])
    
    need = {"begin", "open", "high", "low", "close"}
    if not need.issubset(df.columns): return pd.DataFrame()
    
    df = df.rename(columns={"begin": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    if "Volume" not in df: df["Volume"] = 0
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index().dropna(subset=["Open", "High", "Low", "Close"])[["Open", "High", "Low", "Close", "Volume"]]
