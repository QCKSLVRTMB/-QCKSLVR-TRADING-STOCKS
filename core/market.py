# core/market.py
from __future__ import annotations
import os
import ssl
import time
from datetime import datetime, timedelta, date
from typing import Tuple

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry

from core.config import INDEX_META

# URLs
ISS_SHARES = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off&iss.only=securities,marketdata&limit=1000"
ISS_INDICES = "https://iss.moex.com/iss/engines/stock/markets/index/securities.json?iss.meta=off&iss.only=securities,marketdata"
ISS_CANDLES = "https://iss.moex.com/iss/engines/stock/markets/{market}/securities/{ticker}/candles.json"
ISS_HISTORY = "https://iss.moex.com/iss/history/engines/stock/markets/{market}/securities/{ticker}.json"

@st.cache_resource(show_spinner=False)
def _session() -> requests.Session:
    s = requests.Session()
    
    # ИСПРАВЛЕНИЕ SSL: Отключаем проверку только если явно разрешено в env
    # Это безопасно для локального использования в корпоративной сети
    if os.getenv("MOEX_DISABLE_SSL_VERIFY", "").lower() in ("1", "true", "yes"):
        s.verify = False
        # Подавляем предупреждения InsecureRequestWarning
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        st.sidebar.info("⚠️ Проверка SSL отключена (MOEX_DISABLE_SSL_VERIFY)")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.moex.com/",
        "Connection": "keep-alive",
    }
    s.headers.update(headers)
    
    # Увеличиваем количество попыток и добавляем backoff
    retries = Retry(
        total=5, 
        backoff_factor=1.0, 
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    
    return s

@st.cache_data(ttl=300, show_spinner="Загрузка котировок MOEX...")
def fetch_moex_stocks() -> pd.DataFrame:
    """Получает список акций с основными параметрами."""
    try:
        r = _session().get(ISS_SHARES, timeout=(10, 30))
        r.raise_for_status()
        js = r.json()
        
        sec_cols = js["securities"]["columns"]
        sec_data = js["securities"]["data"]
        mkt_cols = js["marketdata"]["columns"]
        mkt_data = js["marketdata"]["data"]
        
        sec = pd.DataFrame(sec_data, columns=sec_cols)
        mkt = pd.DataFrame(mkt_data, columns=mkt_cols)
        
    except Exception as e:
        st.error(f"Ошибка загрузки списка акций: {e}")
        return pd.DataFrame()

    # Нормализация колонок
    for col in ["LOTSIZE", "MINSTEP", "PREVPRICE", "LISTLEVEL", "ISSUESIZE", "DECIMALS"]:
        if col not in sec.columns:
            sec[col] = 0
    
    for col in ["LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]:
        if col not in mkt.columns:
            mkt[col] = 0
            
    # Безопасное объединение по SECID
    df = sec.merge(
        mkt[["SECID", "LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]], 
        on="SECID", 
        how="left"
    )
    
    # Приведение типов
    num_cols = ["LOTSIZE", "MINSTEP", "PREVPRICE", "LISTLEVEL", "ISSUESIZE", 
                "DECIMALS", "LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        
    # Расчет цены: приоритет LAST, фоллбэк на PREVPRICE
    df["PRICE"] = df["LAST"].where(df["LAST"] > 0, df["PREVPRICE"])
    df["LOT_VALUE"] = df["PRICE"] * df["LOTSIZE"]
    
    # Оставляем только нужные колонки для рейтинга
    keep_cols = ["SECID", "SHORTNAME", "LOTSIZE", "MINSTEP", "PREVPRICE", 
                 "LISTLEVEL", "ISSUESIZE", "DECIMALS", "PRICE", "LOT_VALUE",
                 "LAST", "VALTODAY", "LASTCHANGEPRCNT", "NUMTRADES"]
    return df[[c for c in keep_cols if c in df.columns]]


@st.cache_data(ttl=300, show_spinner="Загрузка индексов...")
def fetch_moex_indices() -> pd.DataFrame:
    try:
        r = _session().get(ISS_INDICES, timeout=(10, 30))
        r.raise_for_status()
        js = r.json()
        
        sec = pd.DataFrame(js.get("securities", {}).get("data", []), 
                           columns=js.get("securities", {}).get("columns", []))
        mkt = pd.DataFrame(js.get("marketdata", {}).get("data", []), 
                           columns=js.get("marketdata", {}).get("columns", []))
                           
    except Exception as e:
        st.warning(f"Индексы недоступны: {e}")
        return pd.DataFrame()

    valid_tickers = ["IMOEX"] + list(INDEX_META.keys())
    
    if "SECID" not in mkt.columns or "CURRENTVALUE" not in mkt.columns:
        return pd.DataFrame()
        
    df = sec[sec["SECID"].isin(valid_tickers)][["SECID", "SHORTNAME"]].merge(
        mkt[["SECID", "CURRENTVALUE", "LASTCHANGEPRCNT"]], 
        on="SECID", 
        how="left"
    )
    
    df["CURRENTVALUE"] = pd.to_numeric(df["CURRENTVALUE"], errors="coerce").fillna(0)
    df["LASTCHANGEPRCNT"] = pd.to_numeric(df["LASTCHANGEPRCNT"], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=None, show_spinner=False)
def fetch_extreme_close(ticker: str, date_val, market: str = "index") -> Tuple[float, str]:
    """Получает цену закрытия на дату экстремума (пятница той недели)."""
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

    # Находим пятницу недели экстремума
    monday = d - timedelta(days=d.isoweekday() - 1)
    friday = monday + timedelta(days=4)
    today = datetime.now()
    
    if friday > today:
        friday = today
        
    frm = monday.strftime("%Y-%m-%d")
    till = friday.strftime("%Y-%m-%d")
    
    if market == "index":
        url = ISS_HISTORY.format(market="index", ticker=ticker)
    else:
        url = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
        
    try:
        r = _session().get(url, params={"from": frm, "till": till, "iss.meta": "off"}, timeout=10)
        r.raise_for_status()
        data = r.json().get("history", {})
        
        if not data or "data" not in data:
            return 0.0, "-"
            
        hist = pd.DataFrame(data["data"], columns=data["columns"])
        
        if hist.empty or "CLOSE" not in hist.columns:
            return 0.0, "-"
            
        last_row = hist.sort_values("TRADEDATE").iloc[-1]
        return float(last_row["CLOSE"]), str(last_row["TRADEDATE"])
        
    except Exception as e:
        # Не спамим ошибкой в UI при загрузке множества тикеров
        return 0.0, "-"


@st.cache_data(ttl=None, show_spinner=False)
def fetch_many_extreme_closes(tickers: list[str], date_val) -> dict[str, float]:
    result = {}
    # Ограничиваем параллельность, чтобы не получить бан от MOEX
    max_workers = min(10, len(tickers)) 
    
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(fetch_extreme_close, t, date_val, "shares"): t 
            for t in tickers
        }
        try:
            for future in concurrent.futures.as_completed(future_to_ticker, timeout=120):
                t = future_to_ticker[future]
                try:
                    price, _ = future.result(timeout=5)
                    result[t] = price
                except Exception:
                    result[t] = 0.0
        except concurrent.futures.TimeoutError:
            pass
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_dividends_dohod(ticker: str) -> dict:
    """Парсинг дивидендов и DSI с dohod.ru"""
    url = f"https://www.dohod.ru/ik/analytics/dividend/{ticker.lower()}"
    result = {"div_12m": 0.0, "dsi": 0.0}
    
    try:
        r = _session().get(url, timeout=(10, 15))
        if r.status_code != 200:
            return result
            
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        
        # Поиск DSI
        for keyword in ["DSI", "стабильности"]:
            matches = re.finditer(rf"{keyword}[^\d]*([\d]+[.,]?[\d]*)", text, re.IGNORECASE)
            for match in matches:
                try:
                    val_str = match.group(1).replace(",", ".")
                    val = float(val_str)
                    # Нормализация: если число > 1, считаем что это проценты
                    if val > 1.0:
                        val = val / 100.0
                    if 0.0 <= val <= 1.0:
                        result["dsi"] = val
                        break
                except ValueError:
                    pass
            if result["dsi"] > 0:
                break
                
        # Поиск дивидендов за 12м
        div_match = re.search(r"Совокупные дивиденды в следующие 12m:\s*([0-9]+[.,]?[0-9]*)\s*руб", text, re.IGNORECASE)
        if div_match:
            result["div_12m"] = float(div_match.group(1).replace(",", "."))
        else:
            div_match_alt = re.search(r"след\s*12m\.?\s*\(прогноз\)\s*\|\s*([0-9]+[.,]?[0-9]*)", text, re.IGNORECASE)
            if div_match_alt:
                result["div_12m"] = float(div_match_alt.group(1).replace(",", "."))
                
    except Exception:
        pass
        
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_many_dividends(tickers: list[str]) -> dict[str, dict]:
    result = {}
    import concurrent.futures
    
    max_workers = min(8, len(tickers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(fetch_dividends_dohod, t): t for t in tickers}
        try:
            for future in concurrent.futures.as_completed(future_to_ticker, timeout=120):
                t = future_to_ticker[future]
                try:
                    result[t] = future.result(timeout=10)
                except Exception:
                    result[t] = {"div_12m": 0.0, "dsi": 0.0}
        except concurrent.futures.TimeoutError:
            pass
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_moex_candles(ticker: str, interval: int, days_back: int = 60, market: str = "shares") -> pd.DataFrame:
    frm = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    till = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    url = ISS_CANDLES.format(market=market, ticker=ticker)
    
    chunks, start = [], 0
    for _ in range(30):
        try:
            r = _session().get(
                url, 
                params={"interval": interval, "from": frm, "till": till, "start": start, "iss.meta": "off"}, 
                timeout=15
            )
            r.raise_for_status()
            block = r.json().get("candles") or {}
        except Exception:
            break
            
        data = block.get("data") or []
        if not data:
            break
            
        chunks.append(pd.DataFrame(data, columns=block["columns"]))
        if len(data) < 500:
            break
        start += 500
        time.sleep(0.2) # Увеличили паузу для надежности
        
    if not chunks:
        return pd.DataFrame()
        
    df = pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["begin"])
    need = {"begin", "open", "high", "low", "close"}
    
    if not need.issubset(df.columns):
        return pd.DataFrame()
        
    df = df.rename(columns={
        "begin": "Date", "open": "Open", "high": "High", 
        "low": "Low", "close": "Close", "volume": "Volume"
    })
    
    if "Volume" not in df:
        df["Volume"] = 0.0
        
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    df = df.set_index("Date").sort_index().dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = df["Volume"].fillna(0.0)
    
    return df[["Open", "High", "Low", "Close", "Volume"]]
