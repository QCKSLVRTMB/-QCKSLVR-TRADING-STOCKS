from __future__ import annotations
import streamlit as st
from datetime import datetime
import pandas as pd
import re
import hashlib
from core import state, storage
from core.config import APP_TITLE
from core.market import fetch_moex_stocks
from tabs.main_table import render_main_tab
from tabs.indices import render_indices
from tabs.rating import render_rating
from tabs.portfolio import render_portfolio
from tabs.rebalance import render_rebalance
from tabs.dashboard import render_dashboard
from tabs.trade_planner import render_trade_planner
from tabs.debug import render_debug
from ui.theme import inject_css, seg

st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")
inject_css()
S = state.get_state()
G = S["global"]
df_stocks = fetch_moex_stocks()


def _sync(key, gkey):
    state.set_global(gkey, st.session_state[key])


def _sync_extreme():
    val = st.session_state.sb_extreme
    try:
        datetime.strptime(val, "%d.%m.%Y")
        state.set_global("extreme_date", val)
    except ValueError:
        st.error("Неверный формат даты. Используйте DD.MM.YYYY")


def _file_hash(f) -> str:
    return hashlib.md5(f.getvalue()).hexdigest()


def _parse_cash_value(val) -> float:
    """Парсинг значения кеша из ячейки Excel."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = re.sub(r'[₽$€£]', '', s).strip()
    s = s.replace(' ', '')
    s = s.replace(',', '.')
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _find_cash_by_keywords(df_raw: pd.DataFrame) -> tuple:
    """Поиск кеша и плеча по ключевым словам."""
    cash_trader = 0.0
    total_cash = 0.0
    margin_loan = 0.0
    cash_keywords = ["кеш", "cash", "рубли", "рубль", "баланс", "свободные"]
    margin_keywords = ["плечо", "маржа", "margin", "кредит", "заём"]
    for idx, row in df_raw.iterrows():
        first_cell = str(row.iloc[0]).strip().lower() if not pd.isna(row.iloc[0]) else ""
        if any(kw in first_cell for kw in cash_keywords):
            for col_idx in range(1, min(5, len(row))):
                val = row.iloc[col_idx]
                parsed = _parse_cash_value(val)
                if parsed > 0:
                    cash_trader = parsed
                    break
        if any(kw in first_cell for kw in margin_keywords):
            for col_idx in range(1, min(5, len(row))):
                val = row.iloc[col_idx]
                parsed = _parse_cash_value(val)
                if parsed > 0:
                    margin_loan = parsed
                    break
    return cash_trader, total_cash, margin_loan


def _parse_rebalance_table(df_raw: pd.DataFrame) -> tuple[list[dict], dict]:
    """Парсинг таблицы ребалансировки из Excel.
    
    Ищет строку с заголовком "Сектор" и читает данные:
    - Столбец G (относительно заголовка): Название сектора
    - Столбец H (относительно заголовка): Процент в портфеле
    - Столбец I (относительно заголовка): Тикеры через пробел
    
    Возвращает (sectors_data, tickers_data).
    """
    sectors_data = []
    tickers_data = {}
    
    # Ищем строку с заголовком "Сектор"
    header_row_idx = None
    header_col_idx = None
    for idx, row in df_raw.iterrows():
        for col_idx, val in enumerate(row.values):
            if pd.notna(val) and "сектор" in str(val).lower().strip():
                header_row_idx = idx
                header_col_idx = col_idx
                break
        if header_row_idx is not None:
            break
    
    if header_row_idx is None:
        return sectors_data, tickers_data
    
    # Определяем индексы столбцов: Сектор, Процент, Тикеры
    sec_col = header_col_idx
    pct_col = header_col_idx + 1
    tickers_col = header_col_idx + 2
    
    # Читаем данные после заголовка
    for idx in range(header_row_idx + 1, len(df_raw)):
        row = df_raw.iloc[idx]
        
        # Проверяем, не дошли ли до строки "ИТОГО"
        first_val = str(row.iloc[0]).strip().lower() if pd.notna(row.iloc[0]) else ""
        if "итого" in first_val:
            break
        
        # Получаем значения из нужных столбцов
        sector_val = row.iloc[sec_col] if sec_col < len(row) else None
        pct_val = row.iloc[pct_col] if pct_col < len(row) else None
        tickers_val = row.iloc[tickers_col] if tickers_col < len(row) else None
        
        if pd.isna(sector_val):
            continue
        
        sector = str(sector_val).strip()
        
        # Проверяем, является ли это названием сектора
        known_sectors = ["Нефтегаз", "Финансовый", "Металлы и добыча", "Энергетика", 
                        "Телекомы", "Потребительский", "Химия", "Инновации",
                        "Транспорт", "ИТ", "Строительство", "Разное"]
        
        if sector not in known_sectors:
            continue
        
        # Парсим процент
        pct = 0.0
        if pd.notna(pct_val):
            try:
                pct = float(str(pct_val).replace(',', '.'))
            except (ValueError, TypeError):
                pass
        
        # Парсим тикеры (могут быть в одной ячейке через пробел)
        tickers = []
        if pd.notna(tickers_val):
            tickers_str = str(tickers_val)
            # Разбиваем по пробелам и фильтруем валидные тикеры
            for t in tickers_str.split():
                t = t.strip().upper()
                if re.match(r'^[A-ZА-Я0-9]{2,10}$', t):
                    tickers.append(t)
        
        sectors_data.append({"Сектор": sector, "Доля, %": pct})
        tickers_data[sector] = tickers
    
    return sectors_data, tickers_data


def _parse_debug_file(df_debug: pd.DataFrame) -> dict:
    """Парсит файл Отладка.xlsx и возвращает словарь overrides.
    Пустые ячейки игнорируются — значения берутся из Источников."""
    overrides = {}
    if df_debug is None or df_debug.empty:
        return overrides
    
    cols = {str(c).strip().lower(): c for c in df_debug.columns}
    t_col = next((c for k, c in cols.items() if 'тикер' in k), None)
    dsi_col = next((c for k, c in cols.items() if 'dsi' in k), None)
    ars_col = next((c for k, c in cols.items() if 'арсагера' in k), None)
    div_col = next((c for k, c in cols.items() if 'див' in k or '12м' in k), None)
    sec_col = next((c for k, c in cols.items() if 'сектор' in k), None)
    
    if not t_col:
        return overrides
    
    for _, row in df_debug.iterrows():
        t = str(row[t_col]).strip().upper() if pd.notna(row[t_col]) else None
        if not t or t in {'ТИКЕР', 'TICKER', 'NAN', '-'}:
            continue
        
        entry = {}
        if dsi_col and pd.notna(row[dsi_col]):
            try:
                val = float(str(row[dsi_col]).replace(',', '.'))
                if val > 0:
                    entry["dsi"] = val
            except:
                pass
        if ars_col and pd.notna(row[ars_col]):
            try:
                val = int(float(str(row[ars_col]).replace(',', '.')))
                if val > 0:
                    entry["ars_group"] = val
            except:
                pass
        if div_col and pd.notna(row[div_col]):
            try:
                val = float(str(row[div_col]).replace(',', '.'))
                if val > 0:
                    entry["div_12m"] = val
            except:
                pass
        if sec_col and pd.notna(row[sec_col]):
            entry["sector"] = str(row[sec_col]).strip()
        
        if entry:
            overrides[t] = entry
    
    return overrides


def _parse_index_div_yield(df_dsi: pd.DataFrame) -> float:
    """Парсит доходность индекса 'Компании стабильных дивидендов' из листа DSI."""
    if df_dsi is None or df_dsi.empty:
        return 0.0
    col_name = next((c for c in df_dsi.columns if 'Акция' in str(c)), None)
    col_yield = next((c for c in df_dsi.columns if 'Доходность' in str(c)), None)
    if not col_name or not col_yield:
        return 0.0
    
    for _, row in df_dsi.iterrows():
        name = str(row[col_name]).strip().lower() if pd.notna(row[col_name]) else ""
        # Ищем "стабильных дивидендов" - более уникальная комбинация
        if 'стабильн' in name and 'дивиденд' in name:
            try:
                yield_val = float(str(row[col_yield]).replace(',', '.'))
                if yield_val > 0:
                    return yield_val
            except:
                pass
    return 0.0


# ============================================================
# Excel-парсеры
# ============================================================
_TICKER_RE = re.compile(r'^[A-ZА-Я0-9]{1,10}$')
_W_ALIASES = {
    "вверх": "вверх", "up": "вверх", "рост": "вверх",
    "вниз": "вниз", "down": "вниз", "падение": "вниз",
    "рейндж": "рейндж", "range": "рейндж", "боковик": "рейндж", "flat": "рейндж",
}


def _norm(text) -> str:
    if pd.isna(text):
        return ""
    return re.sub(r'[^\wа-яё]', '', str(text).strip().lower(), flags=re.IGNORECASE)


def _split_class(raw) -> tuple[str, str]:
    if pd.isna(raw):
        return "", "common"
    s_raw = str(raw).strip().lower()
    s_raw = re.sub(r'\b(оао|пао|зао|ао|ак|ооо|мкпао)\b', '', s_raw).strip()
    s_norm = _norm(s_raw)
    if not s_norm:
        return "", "common"
    for pat in ('-pref', ' pref', '-ап', ', ап', ' ап', '-п', ' п'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m):
                return s_norm[: -len(m)], "preferred"
            return s_norm, "preferred"
    for pat in ('-ord', ' ord', '-ао', ' ао', '-ao', ' ao'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m):
                return s_norm[: -len(m)], "common"
            return s_norm, "common"
    return s_norm, "common"


def _lookup_ticker(name, name_index: dict):
    """Поиск тикера по названию с fallback на любой класс акций."""
    base, cls = _split_class(name)
    if not base:
        return None

    # 1. Точный матч по базе и классу
    t = name_index.get((base, cls))
    if t:
        return t

    # 2. Fallback: ищем по базе с любым классом (приоритет: тот же класс > common > любой)
    best, best_len, best_priority = None, 0, -1
    for (nb, nc), ticker in name_index.items():
        if not nb:
            continue
        if nb.startswith(base) or base.startswith(nb):
            overlap = min(len(nb), len(base))
            if overlap >= 4 and overlap > best_len:
                priority = 2 if nc == cls else (1 if nc == "common" else 0)
                if priority > best_priority or (priority == best_priority and overlap > best_len):
                    best, best_len, best_priority = ticker, overlap, priority

    if best:
        return best

    # 3. Частичное совпадение
    for (nb, nc), ticker in name_index.items():
        if not nb:
            continue
        if (base in nb or nb in base) and min(len(base), len(nb)) >= 3:
            return ticker

    return None


def _parse_arsagera(df_ars) -> tuple[dict, dict]:
    ars_dict, name_index = {}, {}
    if df_ars is None or df_ars.empty:
        return ars_dict, name_index
    for group_num, start_col in enumerate([0, 5, 10, 15], start=1):
        if start_col >= df_ars.shape[1]:
            continue
        for i in range(len(df_ars)):
            t_raw = df_ars.iloc[i, start_col] if start_col < df_ars.shape[1] else None
            n_raw = df_ars.iloc[i, start_col + 1] if start_col + 1 < df_ars.shape[1] else None
            if pd.isna(t_raw) or pd.isna(n_raw):
                continue
            ticker = str(t_raw).strip().upper()
            if not _TICKER_RE.match(ticker) or ticker in {"ТИКЕР", "TICKER"}:
                continue
            name = str(n_raw).strip()
            if not name:
                continue
            if ticker not in ars_dict:
                ars_dict[ticker] = group_num
            base, cls = _split_class(name)
            if base:
                name_index.setdefault((base, cls), ticker)
    return ars_dict, name_index


def _to_float_safe(v):
    """Нормализует число: запятая, пробелы, валюта, проценты, NBSP."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = re.sub(r"[₽$€£%\u00a0\u202f\s]", "", s)
    if "," in s and "." in s:
        s = s.replace(",", "")          # 1,085.00 → 1085.00
    else:
        s = s.replace(",", ".")         # 1085,00  → 1085.00
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _is_12m_period(p) -> bool:
    """'всего 12м' / '12м' / '12 м' / '12мес' / '12 месяцев'. Латиница/кириллица/пробелы."""
    if p is None or (isinstance(p, float) and pd.isna(p)):
        return False
    s = str(p).strip().lower()
    s = s.replace("m", "м")             # латинская m → кириллическая м
    s = s.replace("\u00a0", " ")         # NBSP → обычный пробел
    return ("12м" in s) or ("12 м" in s)


def _parse_dsi(df_dsi, name_index: dict) -> tuple[dict, dict]:
    """DSI + 'всего 12м'. 12м парсится НЕЗАВИСИМО от DSI.
    Возвращает (dsi_dict, div_12m_dict)."""
    dsi_dict: dict = {}
    div_12m_dict: dict = {}
    if df_dsi is None or df_dsi.empty:
        return dsi_dict, div_12m_dict

    def _find_col(*substrs):
        for c in df_dsi.columns:
            cn = str(c).strip().lower()
            if any(s.lower() in cn for s in substrs):
                return c
        return None

    col_name   = _find_col("акци")           # "Акция", "Акции"
    col_dsi    = _find_col("dsi")
    col_period = _find_col("период")
    col_payout = _find_col("выплат")

    if col_name is None:
        return dsi_dict, div_12m_dict

    for _, row in df_dsi.iterrows():
        name = row[col_name]
        if pd.isna(name):
            continue
        ticker = _lookup_ticker(str(name).strip(), name_index)
        if not ticker:
            continue

        # DSI — независимо
        if col_dsi is not None:
            dv = _to_float_safe(row[col_dsi])
            if dv is not None and ticker not in dsi_dict:
                dsi_dict[ticker] = dv

        # 12м — независимо от DSI
        if col_period is not None and col_payout is not None:
            if _is_12m_period(row[col_period]):
                pv = _to_float_safe(row[col_payout])
                if pv is not None and pv > div_12m_dict.get(ticker, -1):
                    div_12m_dict[ticker] = pv

    return dsi_dict, div_12m_dict


def _parse_w_any(xls: pd.ExcelFile) -> dict:
    sheet_name = "W-формации" if "W-формации" in xls.sheet_names else xls.sheet_names[0]
    df_w = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    direction_idx = None
    for i in range(df_w.shape[1]):
        vals = df_w.iloc[:, i].dropna().astype(str).str.lower().str.strip()
        if vals.isin(set(_W_ALIASES.keys())).any():
            direction_idx = i
            break
    if direction_idx is None:
        return {}
    ticker_idx = -1
    if direction_idx > 0:
        left_col = df_w.iloc[:, direction_idx - 1].dropna().astype(str)
        if left_col.str.match(r"^[A-ZА-Я0-9]{2,10}$", na=False).any():
            ticker_idx = direction_idx - 1
    if ticker_idx == -1 and direction_idx < df_w.shape[1] - 1:
        right_col = df_w.iloc[:, direction_idx + 1].dropna().astype(str)
        if right_col.str.match(r"^[A-ZА-Я0-9]{2,10}$", na=False).any():
            ticker_idx = direction_idx + 1
    if ticker_idx == -1:
        return {}
    result = {}
    for _, row in df_w.iterrows():
        t_raw = row.iloc[ticker_idx]
        d_raw = row.iloc[direction_idx]
        if pd.isna(t_raw) or pd.isna(d_raw):
            continue
        ticker = str(t_raw).strip().upper()
        if not _TICKER_RE.match(ticker) or ticker in {"ТИКЕР", "TICKER"}:
            continue
        direction = str(d_raw).strip().lower()
        if direction in _W_ALIASES:
            result[ticker] = _W_ALIASES[direction]
    return result


def _parse_dividends_sheet(xls: pd.ExcelFile) -> tuple[dict, list]:
    """Парсит дивиденды из листа Дивиденды.
    Используется ТОЛЬКО для расчета брутто/нетто и таблицы будущих выплат.
    НЕ используется для расчета дивидендной доходности в рейтинге."""
    sheet_name = next((s for s in xls.sheet_names if "дивиденд" in s.lower()), None)
    if not sheet_name:
        return {}, []
    df = pd.read_excel(xls, sheet_name=sheet_name)
    cols = {str(c).strip().lower(): c for c in df.columns}
    t_col = next((c for k, c in cols.items() if "тикер" in k), None)
    n_col = next((c for k, c in cols.items() if "название" in k or "компания" in k or "наименование" in k), None)
    p_col = next((c for k, c in cols.items() if "период" in k), None)
    v_col = next((c for k, c in cols.items() if "дивиденд" in k and ("руб" in k or "сумма" in k)), None)
    if not v_col:
        v_col = next((c for k, c in cols.items() if "дивиденд" in k), None)
    d_close_col = next((c for k, c in cols.items() if "закрыт" in k or "реестр" in k), None)
    d_pay_col = next((c for k, c in cols.items() if "выплат" in k), None)
    d_buy_col = next((c for k, c in cols.items() if "купить" in k), None)
    if not t_col or not v_col:
        return {}, []

    def parse_date(val):
        if pd.isna(val):
            return None
        try:
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return pd.to_datetime(val, unit="D", origin="1899-12-30")
            s = str(val).strip()
            m = re.search(r"(\d{1,2})[\.\-\/](\d{1,2})[\.\-\/](\d{4})", s)
            if m:
                d, mth, y = m.groups()
                return pd.to_datetime(f"{y}-{mth.zfill(2)}-{d.zfill(2)}")
            m2 = re.search(r"(\d{4})[\.\-\/](\d{1,2})[\.\-\/](\d{1,2})", s)
            if m2:
                y, mth, d = m2.groups()
                return pd.to_datetime(f"{y}-{mth.zfill(2)}-{d.zfill(2)}")
            dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
            return dt if not pd.isna(dt) else None
        except Exception:
            return None

    summed = {}
    div_list = []
    now = pd.Timestamp.now().normalize()
    for _, row in df.iterrows():
        t = str(row[t_col]).strip().upper()
        if not t or t in {"NAN", "-"} or not _TICKER_RE.match(t):
            continue
        dt_check = None
        for col in [d_close_col, d_pay_col, d_buy_col]:
            if col and not pd.isna(row[col]):
                dt_check = parse_date(row[col])
                if dt_check:
                    break
        if dt_check is None or dt_check < now:
            continue
        if pd.isna(row[v_col]):
            continue
        try:
            v_raw = str(row[v_col]).replace(",", ".").replace(" ", "").replace("руб", "").replace("₽", "").strip()
            val = float(v_raw)
        except Exception:
            continue
        summed[t] = summed.get(t, 0.0) + val
        name = str(row[n_col]).strip() if n_col and not pd.isna(row[n_col]) else "-"
        period = str(row[p_col]).strip() if p_col and not pd.isna(row[p_col]) else "-"
        dt_close = parse_date(row[d_close_col]) if d_close_col else None
        dt_pay = parse_date(row[d_pay_col]) if d_pay_col else None
        div_list.append({
            "Тикер": t,
            "Название": name,
            "Период": period,
            "Дивиденд": val,
            "Дата закрытия реестра": dt_close.strftime("%d.%m.%Y") if dt_close else "-",
            "Выплата до...": dt_pay.strftime("%d.%m.%Y") if dt_pay else "-",
        })
    return summed, div_list


def _parse_portfolio_any(df_raw: pd.DataFrame, df_stocks: pd.DataFrame) -> tuple[list[dict], float]:
    """Парсинг портфеля из Excel.
    Приоритет кеша: B34 (кеш трейдера) > B35 (общий кеш по формуле) > 0.
    B36 — маржинальное обеспечение (плечо).
    """
    if df_raw is None or df_raw.empty:
        return [], 0.0

    cash_trader = 0.0
    margin_loan = 0.0
    total_cash = 0.0

    if df_raw.shape[0] >= 36 and df_raw.shape[1] >= 2:
        try:
            val_b34 = df_raw.iloc[33, 1]
            if not pd.isna(val_b34):
                cash_trader = _parse_cash_value(val_b34)

            val_b35 = df_raw.iloc[34, 1]
            if not pd.isna(val_b35):
                total_cash = _parse_cash_value(val_b35)

            val_b36 = df_raw.iloc[35, 1]
            if not pd.isna(val_b36):
                margin_loan = _parse_cash_value(val_b36)
        except (ValueError, TypeError, IndexError) as e:
            st.warning(f"Не удалось прочитать ячейки B34-B36: {e}")

    if cash_trader == 0.0 and total_cash == 0.0:
        cash_trader, total_cash, margin_loan = _find_cash_by_keywords(df_raw)

    cash_val = cash_trader if cash_trader > 0 else total_cash

    cols = {str(c).strip().lower(): c for c in df_raw.columns}
    t_candidates = [c for k, c in cols.items() if "тикер" in k]
    p_candidates = [c for k, c in cols.items() if "твх" in k or "средн" in k or "цена входа" in k]
    q_candidates = [c for k, c in cols.items() if "лотов" in k or "колич" in k or "кол-во" in k]
    s_candidates = [c for k, c in cols.items() if "сектор" in k]

    if not t_candidates or not p_candidates or not q_candidates:
        return [], cash_val

    t_col = t_candidates[0]
    p_col = p_candidates[0]
    s_col = s_candidates[0] if s_candidates else None
    q_col = q_candidates[0]

    max_valid = -1
    for cand in q_candidates:
        valid_count = pd.to_numeric(df_raw[cand], errors="coerce").notna().sum()
        if valid_count > max_valid:
            max_valid = valid_count
            q_col = cand

    valid_tickers = set(df_stocks["SECID"].tolist()) if df_stocks is not None and not df_stocks.empty else set()
    records = []
    for _, r in df_raw.iterrows():
        t = str(r[t_col]).strip().upper()
        if not _TICKER_RE.match(t):
            continue
        if t in {"ТИКЕР", "TICKER", "NAN", "-"}:
            continue
        if valid_tickers and t not in valid_tickers:
            continue
        try:
            p = float(str(r[p_col]).replace(",", "."))
            q = int(float(str(r[q_col]).replace(",", ".")))
        except (ValueError, TypeError):
            continue
        if p <= 0 or q <= 0:
            continue
        sec = str(r[s_col]).strip() if s_col and not pd.isna(r[s_col]) else "Разное"
        records.append({"Тикер": t, "ТВХ": p, "Лотов": q, "Сектор": sec})

    return records, cash_val


# ============================================================
# Сайдбар
# ============================================================
with st.sidebar:
    st.header("Настройки")
    st.text_input("Экстремум", value=G["extreme_date"], key="sb_extreme", on_change=_sync_extreme)
    st.number_input("Ставка ЦБ, %", value=float(G["cb_rate"]), step=0.25, format="%.2f", key="sb_cb", on_change=_sync, args=("sb_cb", "cb_rate"))
    st.number_input("Резерв кэша, %", value=float(G["cash_reserve"]), step=1.0, key="sb_cash", on_change=_sync, args=("sb_cash", "cash_reserve"))
    st.checkbox("Мобильный вид", value=G.get("mobile_view", False), key="sb_mobile", on_change=_sync, args=("sb_mobile", "mobile_view"))

    st.divider()
    st.header("Импорт / Экспорт")
    w_file = st.file_uploader("Импорт W-формаций", type=["xlsx", "xls"], key="upl_w")
    if w_file is not None:
        _h = _file_hash(w_file)
        if st.session_state.get("_w_hash") != _h:
            try:
                xls = pd.ExcelFile(w_file)
                new_w = _parse_w_any(xls)
                if new_w:
                    state.set_global("w_formations", new_w)
                    st.session_state["_w_hash"] = _h
                    st.success(f"W-формации загружены: {len(new_w)}")
                    state.autosave()
                else:
                    st.error("Не найдены направления.")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    sources_file = st.file_uploader("Импорт Источников", type=["xlsx", "xls"], key="upl_src")
    if sources_file is not None:
        _h = _file_hash(sources_file)
        if st.session_state.get("_src_hash") != _h:
            try:
                xls = pd.ExcelFile(sources_file)
                ars_dict, name_index = {}, {}
                if "Рейтинг арсагера" in xls.sheet_names:
                    ars_dict, name_index = _parse_arsagera(pd.read_excel(xls, sheet_name="Рейтинг арсагера", header=None))
                dsi_dict = {}
                div_12m_from_dsi = {}
                index_div_yield = 0.0
                if "ДОХОД DSI" in xls.sheet_names:
                    df_dsi = pd.read_excel(xls, sheet_name="ДОХОД DSI")
                    dsi_dict, div_12m_from_dsi = _parse_dsi(df_dsi, name_index)
                    # Парсим доходность индекса "Компании стабильных дивидендов"
                    index_div_yield = _parse_index_div_yield(df_dsi)
                div_dict, div_list = {}, []
                if any("дивиденд" in s.lower() for s in xls.sheet_names):
                    div_dict, div_list = _parse_dividends_sheet(xls)
                    div_dict["_list"] = div_list
                # Сохраняем дивиденды из листа Дивиденды (для брутто/нетто и будущих выплат)
                state.set_global("future_dividends", div_dict)
                state.set_global("future_div_list", div_list)
                # Сохраняем дивиденды "всего 12м" из DSI (для расчета доходности)
                if div_12m_from_dsi:
                    state.set_global("div_12m_from_dsi", div_12m_from_dsi)
                fund_data = {t: {"ars_group": ars_dict.get(t, 0), "dsi": dsi_dict.get(t, 0.0)} for t in set(ars_dict) | set(dsi_dict)}
                if fund_data or div_dict:
                    state.set_global("fundamental_data", fund_data)
                # Сохраняем доходность индекса
                if index_div_yield > 0:
                    state.set_global("index_div_yield", index_div_yield)
                st.session_state["_src_hash"] = _h
                msg = f"Загружено {len(fund_data)} записей."
                if div_list:
                    msg += f" Будущих дивидендов: {len(div_list)}."
                if div_12m_from_dsi:
                    msg += f" Дивидендов '12м' из DSI: {len(div_12m_from_dsi)}."
                    lkoh_12m = div_12m_from_dsi.get("LKOH")
                    if lkoh_12m:
                        msg += f" LKOH 12м = {lkoh_12m:g}."
                    else:
                        msg += " ⚠ LKOH не найден в 12м."
                if index_div_yield > 0:
                    msg += f" Доходность индекса стаб.див: {index_div_yield*100:.2f}%."
                st.success(msg)
                state.autosave()
            except Exception as e:
                st.error(f"Ошибка: {e}")

    # === Импорт файла Отладка ===
    debug_file = st.file_uploader("Импорт Отладка", type=["xlsx", "xls"], key="upl_debug")
    if debug_file is not None:
        _h = _file_hash(debug_file)
        if st.session_state.get("_debug_hash") != _h:
            try:
                df_debug = pd.read_excel(debug_file)
                new_overrides = _parse_debug_file(df_debug)
                if new_overrides:
                    state.set_global("ticker_overrides", new_overrides)
                    st.session_state["_debug_hash"] = _h
                    st.success(f"Отладка загружена: {len(new_overrides)} корректировок")
                    state.autosave()
                else:
                    st.error("Не найдены тикеры или корректировки.")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    port_file = st.file_uploader("Импорт Портфеля", type=["xlsx", "xls"], key="upl_port")
    if port_file is not None:
        _h = _file_hash(port_file)
        if st.session_state.get("_port_hash") != _h:
            try:
                df_raw = pd.read_excel(port_file)
                records, cash = _parse_portfolio_any(df_raw, df_stocks)
                if records:
                    state.set_global("portfolio_data", records)
                    state.set_global("portfolio_cash_file", cash)
                    state.set_global("portfolio_cash", cash)
                    st.session_state["ui_cash_rub"] = cash
                    
                    # === Парсинг таблицы ребалансировки ===
                    rebal_sectors, rebal_tickers = _parse_rebalance_table(df_raw)
                    if rebal_sectors:
                        state.set_global("rebal_sectors_data", rebal_sectors)
                        state.set_global("rebal_tickers_data", rebal_tickers)
                        st.session_state["rebal_sectors"] = pd.DataFrame(rebal_sectors)
                        st.session_state["rebal_tickers"] = rebal_tickers
                        # Очищаем кэш multiselect, чтобы подтянулись новые значения
                        for k in list(st.session_state.keys()):
                            if k.startswith("tags_"):
                                del st.session_state[k]
                        st.success(f"Портфель загружен: {len(records)} позиций, кеш {cash:.0f} ₽, ребалансировка: {len(rebal_sectors)} секторов")
                    else:
                        st.success(f"Портфель загружен: {len(records)} позиций, кеш {cash:.0f} ₽")
                    
                    st.session_state["_port_hash"] = _h
                    state.autosave()
                else:
                    st.error("Не найдены колонки Тикер / ТВХ / Лотов.")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    if st.button("Подготовить экспорт JSON"):
        st.session_state["_export_requested"] = True

    blob = st.session_state.get("_export_blob")
    if blob:
        st.download_button("Скачать JSON", data=blob, file_name="backup.json", mime="application/json")

    json_file = st.file_uploader("Импорт JSON", type=["json"])
    if json_file and st.button("Применить бэкап"):
        parsed = storage.loads(json_file.getvalue().decode("utf-8"))
        if parsed:
            state.replace_state(parsed)

            portfolio_cash = parsed.get("global", {}).get("portfolio_cash", 0.0)
            if portfolio_cash > 0:
                st.session_state["ui_cash_rub"] = float(portfolio_cash)
                portfolio_data = parsed.get("global", {}).get("portfolio_data", [])
                if portfolio_data:
                    stocks_value = sum(p.get("ТВХ", 0) * p.get("Лотов", 0) for p in portfolio_data)
                    total = stocks_value + portfolio_cash
                    pct = (portfolio_cash / total * 100) if total > 0 else 20.0
                    st.session_state["ui_cash_pct"] = float(pct)

            keys_to_delete = ["ui_cash_rub", "ui_cash_pct", "rebal_sectors", "rebal_tickers", "plan_ticker"]
            for k in list(st.session_state.keys()):
                if k.startswith("tags_") or k in keys_to_delete:
                    del st.session_state[k]

            if "rebal_sectors_data" in parsed["global"]:
                st.session_state["rebal_sectors"] = pd.DataFrame(parsed["global"]["rebal_sectors_data"])
            if "rebal_tickers_data" in parsed["global"]:
                st.session_state["rebal_tickers"] = parsed["global"]["rebal_tickers_data"]

            st.success("Загружено!")
            st.rerun()


# ============================================================
# Вкладки
# ============================================================
tab_market, tab_rating, tab_indices, tab_portfolio, tab_dashboard, tab_rebalance, tab_debug, tab_calc = st.tabs([
    "Обзор", "Рейтинг", "Индексы", "Портфель", "Дашборд", "Ребалансировка", "Отладка", "Калькулятор",
])

with tab_market:
    try:
        render_main_tab(df_stocks=df_stocks, deposit=state.g("portfolio_cash", 0))
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_rating:
    try:
        render_rating()
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_indices:
    try:
        render_indices()
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_portfolio:
    try:
        render_portfolio(df_stocks=df_stocks)
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_dashboard:
    try:
        render_dashboard(df_stocks=df_stocks)
    except Exception as e:
        st.error(f"Ошибка в Дашборде: {e}")

with tab_rebalance:
    try:
        render_rebalance()
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_debug:
    try:
        render_debug()
    except Exception as e:
        st.error(f"Ошибка: {e}")

with tab_calc:
    active_tickers = G.get("active_tickers", [])
    portfolio_data = G.get("portfolio_data", [])
    portfolio_tickers = [p["Тикер"] for p in portfolio_data if "Тикер" in p]
    all_tickers = list(dict.fromkeys(active_tickers + portfolio_tickers))
    if not all_tickers:
        st.info("Выберите тикер на вкладке 'Обзор' или загрузите Портфель.")
    else:
        active = seg("Инструмент", all_tickers, key="plan_ticker", default=all_tickers[0])
        if not active or active not in all_tickers:
            active = all_tickers[0]
        try:
            render_trade_planner(active, df_stocks)
        except Exception as e:
            st.error(f"Ошибка: {e}")

state.autosave()


# ============================================================
# Логика экспорта в самом конце
# ============================================================
if st.session_state.get("_export_requested"):
    st.session_state["_export_blob"] = storage.dumps(S)
    st.session_state["_export_requested"] = False
    st.rerun()
