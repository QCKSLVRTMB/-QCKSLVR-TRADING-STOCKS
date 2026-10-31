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

# ============================================================
# Excel-парсеры
# ============================================================
_TICKER_RE = re.compile(r'^[A-ZА-Я0-9]{1,10}$')

_W_ALIASES = {
    "вверх": "вверх", "up": "вверх", "рост": "вверх",
    "вниз":  "вниз",  "down": "вниз", "падение": "вниз",
    "рейндж": "рейндж", "range": "рейндж", "боковик": "рейндж", "flat": "рейндж",
}

def _norm(text) -> str:
    if pd.isna(text): return ""
    return re.sub(r'[^\wа-яё]', '', str(text).strip().lower(), flags=re.IGNORECASE)

def _split_class(raw) -> tuple[str, str]:
    if pd.isna(raw): return "", "common"
    s_raw = str(raw).strip().lower()
    s_raw = re.sub(r'\b(оао|пао|зао|ао|ак|ооо|мкпао)\b', '', s_raw).strip()
    s_norm = _norm(s_raw)
    if not s_norm: return "", "common"
    
    for pat in ('-pref', ' pref', '-ап', ', ап', ' ап', '-п', ' п'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m): return s_norm[:-len(m)], 'preferred'
            return s_norm, 'preferred'
    for pat in ('-ord', ' ord', '-ао', ' ао', '-ao', ' ao'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m): return s_norm[:-len(m)], 'common'
            return s_norm, 'common'
    return s_norm, 'common'

def _lookup_ticker(name, name_index: dict):
    base, cls = _split_class(name)
    if not base: return None
    t = name_index.get((base, cls))
    if t: return t
    best, best_len = None, 0
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb: continue
        if nb.startswith(base) or base.startswith(nb):
            overlap = min(len(nb), len(base))
            if overlap >= 4 and overlap > best_len:
                best, best_len = ticker, overlap
    if best: return best
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb: continue
        if (base in nb or nb in base) and min(len(base), len(nb)) >= 3:
            return ticker
    return None

def _parse_arsagera(df_ars) -> tuple[dict, dict]:
    ars_dict, name_index = {}, {}
    if df_ars is None or df_ars.empty: return ars_dict, name_index
    for group_num, start_col in enumerate([0, 5, 10, 15], start=1):
        if start_col >= df_ars.shape[1]: continue
        for i in range(len(df_ars)):
            t_raw = df_ars.iloc[i, start_col] if start_col < df_ars.shape[1] else None
            n_raw = df_ars.iloc[i, start_col + 1] if start_col + 1 < df_ars.shape[1] else None
            if pd.isna(t_raw) or pd.isna(n_raw): continue
            ticker = str(t_raw).strip().upper()
            if not _TICKER_RE.match(ticker) or ticker in {'ТИКЕР', 'TICKER'}: continue
            name = str(n_raw).strip()
            if not name: continue
            if ticker not in ars_dict: ars_dict[ticker] = group_num
            base, cls = _split_class(name)
            if base: name_index.setdefault((base, cls), ticker)
    return ars_dict, name_index

def _parse_dsi(df_dsi, name_index: dict) -> dict:
    dsi_dict = {}
    if df_dsi is None or df_dsi.empty: return dsi_dict
    col_name = next((c for c in df_dsi.columns if 'Акция' in str(c)), None)
    col_dsi  = next((c for c in df_dsi.columns if 'DSI' in str(c)), None)
    if not col_name or not col_dsi: return dsi_dict
    for _, row in df_dsi.iterrows():
        name = row[col_name]
        dsi_val = row[col_dsi]
        if pd.isna(name) or pd.isna(dsi_val): continue
        ticker = _lookup_ticker(name, name_index)
        if ticker and ticker not in dsi_dict:
            try: dsi_dict[ticker] = float(dsi_val)
            except (TypeError, ValueError): continue
    return dsi_dict

def _parse_w_any(xls: pd.ExcelFile) -> dict:
    sheet_name = 'W-формации' if 'W-формации' in xls.sheet_names else xls.sheet_names[0]
    df_w = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    direction_idx = None
    for i in range(df_w.shape[1]):
        vals = df_w.iloc[:, i].dropna().astype(str).str.lower().str.strip()
        if vals.isin(set(_W_ALIASES.keys())).any():
            direction_idx = i
            break
    if direction_idx is None: return {}
    ticker_idx = -1
    if direction_idx > 0:
        left_col = df_w.iloc[:, direction_idx - 1].dropna().astype(str)
        if left_col.str.match(r'^[A-ZА-Я0-9]{2,10}$', na=False).any():
            ticker_idx = direction_idx - 1
    if ticker_idx == -1 and direction_idx < df_w.shape[1] - 1:
        right_col = df_w.iloc[:, direction_idx + 1].dropna().astype(str)
        if right_col.str.match(r'^[A-ZА-Я0-9]{2,10}$', na=False).any():
            ticker_idx = direction_idx + 1
    if ticker_idx == -1: return {}
    result = {}
    for _, row in df_w.iterrows():
        t_raw = row.iloc[ticker_idx]
        d_raw = row.iloc[direction_idx]
        if pd.isna(t_raw) or pd.isna(d_raw): continue
        ticker = str(t_raw).strip().upper()
        if not _TICKER_RE.match(ticker) or ticker in {'ТИКЕР', 'TICKER'}: continue
        direction = str(d_raw).strip().lower()
        if direction in _W_ALIASES: result[ticker] = _W_ALIASES[direction]
    return result

def _parse_dividends_sheet(xls: pd.ExcelFile) -> tuple[dict, list]:
    sheet_name = next((s for s in xls.sheet_names if 'дивиденд' in s.lower()), None)
    if not sheet_name: return {}, []
    df = pd.read_excel(xls, sheet_name=sheet_name)
    
    # Жестко заданные индексы, как вы указали
    if len(df.columns) < 9:
        return {}, []
        
    t_col = df.columns[1]       # Тикер
    n_col = df.columns[0]       # Название
    p_col = df.columns[2]       # Период
    v_col = df.columns[3]       # Дивиденд, руб
    
    d_close_col = df.columns[7] # Дата закрытия реестра
    d_pay_col = df.columns[8]   # Выплата до
    
    def parse_date(val):
        if pd.isna(val): return None
        try:
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                return pd.to_datetime(val, unit='D', origin='1899-12-30')
            
            s = str(val).strip()
            # Жестко ищем DD.MM.YYYY
            m = re.search(r'(\d{1,2})[\.\-\/](\d{1,2})[\.\-\/](\d{4})', s)
            if m:
                d, mth, y = m.groups()
                return pd.to_datetime(f"{y}-{mth.zfill(2)}-{d.zfill(2)}")
            
            # Ищем YYYY-MM-DD
            m2 = re.search(r'(\d{4})[\.\-\/](\d{1,2})[\.\-\/](\d{1,2})', s)
            if m2:
                y, mth, d = m2.groups()
                return pd.to_datetime(f"{y}-{mth.zfill(2)}-{d.zfill(2)}")
                
            dt = pd.to_datetime(s, dayfirst=True, errors='coerce')
            return dt if not pd.isna(dt) else None
        except:
            return None

    summed = {}
    div_list = []
    now = pd.Timestamp.now().normalize()
    
    for _, row in df.iterrows():
        t = str(row[t_col]).strip().upper()
        if not t or t in {'NAN', '-'} or not _TICKER_RE.match(t): 
            continue
        
        dt_check = None
        for col in [d_close_col, d_pay_col]:
            if not pd.isna(row[col]):
                dt_check = parse_date(row[col])
                if dt_check:
                    break
                    
        if dt_check is None or dt_check < now:
            continue
            
        if pd.isna(row[v_col]): continue
        
        try:
            v_raw = str(row[v_col]).replace(',', '.').replace(' ', '').replace('руб', '').replace('₽', '').strip()
            val = float(v_raw)
        except:
            continue
            
        summed[t] = summed.get(t, 0.0) + val
        
        name = str(row[n_col]).strip() if not pd.isna(row[n_col]) else "-"
        period = str(row[p_col]).strip() if not pd.isna(row[p_col]) else "-"
        
        dt_close = parse_date(row[d_close_col])
        dt_pay = parse_date(row[d_pay_col])
        
        div_list.append({
            "Тикер": t,
            "Название": name,
            "Период": period,
            "Дивиденд": val,
            "Дата закрытия реестра": dt_close.strftime('%d.%m.%Y') if dt_close else "-",
            "Выплата до...": dt_pay.strftime('%d.%m.%Y') if dt_pay else "-"
        })
            
    return summed, div_list

def _parse_portfolio_any(df_raw: pd.DataFrame, df_stocks: pd.DataFrame) -> tuple[list[dict], float]:
    if df_raw is None or df_raw.empty: return [], 0.0
    
    cols = {str(c).strip().lower(): c for c in df_raw.columns}
    t_candidates = [c for k, c in cols.items() if 'тикер' in k]
    p_candidates = [c for k, c in cols.items() if 'твх' in k or 'средн' in k or 'цена входа' in k]
    q_candidates = [c for k, c in cols.items() if 'лотов' in k or 'колич' in k or 'кол-во' in k]
    s_candidates = [c for k, c in cols.items() if 'сектор' in k]
    
    if not t_candidates or not p_candidates or not q_candidates: 
        return [], 0.0
        
    t_col = t_candidates[0]
    p_col = p_candidates[0]
    s_col = s_candidates[0] if s_candidates else None
    
    q_col = q_candidates[0]
    max_valid = -1
    for cand in q_candidates:
        valid_count = pd.to_numeric(df_raw[cand], errors='coerce').notna().sum()
        if valid_count > max_valid:
            max_valid = valid_count
            q_col = cand
            
    valid_tickers = set(df_stocks["SECID"].tolist()) if df_stocks is not None and not df_stocks.empty else set()
    
    records = []
    for _, r in df_raw.iterrows():
        t = str(r[t_col]).strip().upper()
        if not _TICKER_RE.match(t): continue
        if t in {'ТИКЕР', 'TICKER', 'NAN', '-'}: continue
        if valid_tickers and t not in valid_tickers: continue
        
        try:
            p = float(str(r[p_col]).replace(',', '.'))
            q = int(float(str(r[q_col]).replace(',', '.')))
        except (ValueError, TypeError): continue
        
        if p <= 0 or q <= 0: continue
        
        sec = str(r[s_col]).strip() if s_col and not pd.isna(r[s_col]) else "Разное"
        records.append({"Тикер": t, "ТВХ": p, "Лотов": q, "Сектор": sec})
        
    cash_val = 0.0
    for _, row in df_raw.iterrows():
        val_a = str(row.iloc[0]).strip().lower() if not pd.isna(row.iloc[0]) else ""
        if val_a in ("рубли", "рубль", "кеш", "cash"):
            for cell in row.values[1:]:
                try:
                    val = float(str(cell).replace(',', '.'))
                    if val >= 0:
                        cash_val = val
                        break
                except (ValueError, TypeError):
                    continue
                    
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
            except Exception as e: st.error(f"Ошибка: {e}")

    sources_file = st.file_uploader("Импорт Источников", type=["xlsx", "xls"], key="upl_src")
    if sources_file is not None:
        _h = _file_hash(sources_file)
        if st.session_state.get("_src_hash") != _h:
            try:
                xls = pd.ExcelFile(sources_file)
                ars_dict, name_index = {}, {}
                if 'Рейтинг арсагера' in xls.sheet_names:
                    ars_dict, name_index = _parse_arsagera(pd.read_excel(xls, sheet_name='Рейтинг арсагера', header=None))
                dsi_dict = {}
                if 'ДОХОД DSI' in xls.sheet_names:
                    dsi_dict = _parse_dsi(pd.read_excel(xls, sheet_name='ДОХОД DSI'), name_index)
                
                div_dict, div_list = {}, []
                if any('дивиденд' in s.lower() for s in xls.sheet_names):
                    div_dict, div_list = _parse_dividends_sheet(xls)
                    
                    # Сохраняем список прямо в словарь, чтобы он не терялся при перезагрузке
                    div_dict["_list"] = div_list
                    state.set_global("future_dividends", div_dict)
                
                fund_data = {t: {"ars_group": ars_dict.get(t, 0), "dsi": dsi_dict.get(t, 0.0)} for t in set(ars_dict) | set(dsi_dict)}
                if fund_data or div_dict:
                    state.set_global("fundamental_data", fund_data)
                    st.session_state["_src_hash"] = _h
                    msg = f"Загружено {len(fund_data)} записей."
                    if div_list: msg += f" Будущих дивидендов: {len(div_list)}."
                    st.success(msg)
                    state.autosave()
                else:
                    st.error("Загружено 0 записей.")
            except Exception as e: st.error(f"Ошибка: {e}")

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
                    st.session_state["_port_hash"] = _h
                    st.success(f"Портфель загружен: {len(records)} позиций, кеш {cash:.0f} ₽")
                    state.autosave()
                else:
                    st.error("Не найдены колонки Тикер / ТВХ / Лотов.")
            except Exception as e: st.error(f"Ошибка: {e}")

    if st.button("Подготовить экспорт JSON"):
        st.session_state["_export_blob"] = storage.dumps(S)
    blob = st.session_state.get("_export_blob")
    if blob:
        st.download_button("Скачать JSON", data=blob, file_name="backup.json", mime="application/json")

    json_file = st.file_uploader("Импорт JSON", type=["json"])
    if json_file and st.button("Применить бэкап"):
        parsed = storage.loads(json_file.getvalue().decode("utf-8"))
        if parsed:
            state.replace_state(parsed)
            if "rebal_sectors_data" in parsed["global"]:
                st.session_state["rebal_sectors"] = pd.DataFrame(parsed["global"]["rebal_sectors_data"])
            if "rebal_tickers_data" in parsed["global"]:
                st.session_state["rebal_tickers"] = parsed["global"]["rebal_tickers_data"]
            st.success("Загружено!")
            st.rerun()

# ============================================================
# Вкладки
# ============================================================
tab_market, tab_rating, tab_indices, tab_portfolio, tab_dashboard, tab_rebalance, tab_calc = st.tabs([
    "Обзор", "Рейтинг", "Индексы", "Портфель", "Дашборд", "Ребалансировка", "Калькулятор"
])

with tab_market:
    try: render_main_tab(df_stocks=df_stocks, deposit=state.g("portfolio_cash", 0))
    except Exception as e: st.error(f"Ошибка: {e}")

with tab_rating:
    try: render_rating()
    except Exception as e: st.error(f"Ошибка: {e}")

with tab_indices:
    try: render_indices()
    except Exception as e: st.error(f"Ошибка: {e}")

with tab_portfolio:
    try: render_portfolio(df_stocks=df_stocks)
    except Exception as e: st.error(f"Ошибка: {e}")

with tab_dashboard:
    try: render_dashboard(df_stocks=df_stocks)
    except Exception as e: st.error(f"Ошибка в Дашборде: {e}")

with tab_rebalance:
    try: render_rebalance()
    except Exception as e: st.error(f"Ошибка: {e}")

with tab_calc:
    active_tickers = G.get("active_tickers", [])
    if not active_tickers:
        st.info("Выберите тикер на вкладке 'Обзор'.")
    else:
        active = seg("Инструмент", active_tickers, key="plan_ticker", default=active_tickers[0])
        if not active or active not in active_tickers: active = active_tickers[0]
        try: render_trade_planner(active, df_stocks)
        except Exception as e: st.error(f"Ошибка: {e}")

state.autosave()
