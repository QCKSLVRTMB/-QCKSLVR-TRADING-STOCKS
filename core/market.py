from __future__ import annotations
from datetime import datetime, timedelta, date
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter, Retry
import time
from bs4 import BeautifulSoup
import re
from core.config import INDEX_META

ISS_SHARES = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off&iss.only=securities,marketdata&limit=1000"
ISS_INDICES = "https://iss.moex.com/iss/engines/stock/markets/index/securities.json?iss.meta=off&iss.only=securities,marketdata"
ISS_CANDLES = "https://iss.moex.com/iss/engines/stock/markets/{market}/securities/{ticker}/candles.json"
ISS_HISTORY = "https://iss.moex.com/iss/history/engines/stock/markets/{market}/securities/{ticker}.json"

@st.cache_resource(show_spinner=False)
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
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

@st.cache_data(ttl=None, show_spinner=False)
def fetch_all_closes_on_date(date_val) -> dict[str, float]:
    try:
        if isinstance(date_val, str):
            d = datetime.strptime(date_val, "%d.%m.%Y")
        elif isinstance(date_val, datetime):
            d = date_val
        elif isinstance(date_val, date):
            d = datetime.combine(date_val, datetime.min.time())
        else:
            return {}

        monday = d - timedelta(days=d.isoweekday() - 1)
        friday = monday + timedelta(days=4)
        today = datetime.now()
        if friday > today: friday = today

        frm, till = monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d")
        
        url = "https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities.json"
        r = _session().get(url, params={"from": frm, "till": till, "iss.meta": "off", "limit": 1000}, timeout=15)
        js = r.json()
        hist = pd.DataFrame(js["history"]["data"], columns=js["history"]["columns"])
        if hist.empty: return {}
        
        hist["TRADEDATE"] = pd.to_datetime(hist["TRADEDATE"])
        hist = hist.sort_values("TRADEDATE").groupby("SECID").last().reset_index()
        return dict(zip(hist["SECID"], hist["CLOSE"]))
    except Exception:
        return {}

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dividends_dohod(ticker: str) -> dict:
    url = f"https://www.dohod.ru/ik/analytics/dividend/{ticker.lower()}"
    result = {"div_12m": 0.0, "dsi": 0.0}
    
    try:
        r = _session().get(url, timeout=15)
        if r.status_code != 200:
            return result

        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)

        # 1. Поиск DSI (ищем "индекс DSI" и берем первое число после него)
        dsi_match = re.search(r'индекс\s*DSI[^0-9]*([0-9]+[.,][0-9]+)', text, re.IGNORECASE)
        if dsi_match:
            result["dsi"] = float(dsi_match.group(1).replace(',', '.'))
        else:
            # Резервный вариант: ищем просто "DSI" и число
            dsi_match_alt = re.search(r'DSI[^0-9]*([0-9]+[.,][0-9]+)', text, re.IGNORECASE)
            if dsi_match_alt:
                result["dsi"] = float(dsi_match_alt.group(1).replace(',', '.'))

        # 2. Поиск суммы дивидендов за 12 месяцев
        div_match = re.search(r'Совокупные дивиденды в следующие 12m:\s*([0-9]+[.,]?[0-9]*)\s*руб', text, re.IGNORECASE)
        if div_match:
            result["div_12m"] = float(div_match.group(1).replace(',', '.'))

        return result
    except Exception:
        return result

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dividends_smartlab(ticker: str) -> dict:
    return {"div_gross": 0.0, "div_net": 0.0, "tax": 0.13}

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
