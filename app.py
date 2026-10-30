from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import state, storage
from core.config import APP_TITLE
from core.market import fetch_moex_stocks
from tabs.main_table import render_main_tab
from tabs.indices import render_indices
from tabs.rating import render_rating
from tabs.portfolio import render_portfolio
from tabs.trade_planner import render_trade_planner
from ui.theme import inject_css, seg

st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")
inject_css()

S = state.get_state()
G = S["global"]

# df_stocks нужен и в sidebar (валидация тикеров при загрузке портфеля)
df_stocks = fetch_moex_stocks()


# ============================================================
# Хелперы
# ============================================================
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
    if pd.isna(text):
        return ""
    return re.sub(r'[^\wа-яё]', '', str(text).strip().lower(), flags=re.IGNORECASE)


def _split_class(raw) -> tuple[str, str]:
    """'Сургутнефтегаз, ап' → ('сургутнефтегаз','preferred'); 'Сбербанк России' → ('сбербанкроссии','common')"""
    if pd.isna(raw):
        return "", "common"
    s_raw = str(raw).strip().lower()
    s_norm = _norm(s_raw)
    if not s_norm:
        return "", "common"
    for pat in ('-pref', ' pref', '-ап', ', ап', ' ап', '-п', ' п'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m):
                return s_norm[:-len(m)], 'preferred'
            return s_norm, 'preferred'
    for pat in ('-ord', ' ord', '-ао', ' ао', '-ao', ' ao'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _norm(pat)
            if m and s_norm.endswith(m):
                return s_norm[:-len(m)], 'common'
            return s_norm, 'common'
    return s_norm, 'common'


def _lookup_ticker(name, name_index: dict):
    """DSI-название → тикер: exact → prefix → substring."""
    base, cls = _split_class(name)
    if not base:
        return None
    t = name_index.get((base, cls))
    if t:
        return t
    best, best_len = None, 0
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb:
            continue
        if nb.startswith(base) or base.startswith(nb):
            overlap = min(len(nb), len(base))
            if overlap >= 4 and overlap > best_len:
                best, best_len = ticker, overlap
    if best:
        return best
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb:
            continue
        if (base in nb or nb in base) and min(len(base), len(nb)) >= 3:
            return ticker
    return None


def _parse_arsagera(df_ars) -> tuple[dict, dict]:
    """4 горизонтальных блока A-D / F-I / K-N / P-S.
       Возвращает ars_dict={ticker: group(1..4)} и name_index={(base, cls): ticker}."""
    ars_dict, name_index = {}, {}
    if df_ars is None or df_ars.empty:
        return ars_dict, name_index

    for group_num, start_col in enumerate([0, 5, 10, 15], start=1):
        if start_col >= df_ars.shape[1]:
            continue
        for i in range(2, len(df_ars)):
            t_raw = df_ars.iloc[i, start_col] if start_col < df_ars.shape[1] else None
            n_raw = df_ars.iloc[i, start_col + 1] if start_col + 1 < df_ars.shape[1] else None
            if pd.isna(t_raw) or pd.isna(n_raw):
                continue
            ticker = str(t_raw).strip().upper()
            if not _TICKER_RE.match(ticker):
                continue
            if ticker in {'ТИКЕР', 'TICKER'}:
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


def _parse_dsi(df_dsi, name_index: dict) -> dict:
    """Колонка B = Название, колонка G = DSI. Возвращает {ticker: value_0_to_1}."""
    dsi_dict = {}
    if df_dsi is None or df_dsi.empty:
        return dsi_dict

    col_name = next((c for c in df_dsi.columns if 'Акция' in str(c)), None)
    col_dsi  = next((c for c in df_dsi.columns if 'DSI' in str(c)), None)
    if not col_name or not col_dsi:
        return dsi_dict

    for _, row in df_dsi.iterrows():
        name = row[col_name]
        dsi_val = row[col_dsi]
        if pd.isna(name) or pd.isna(dsi_val):
            continue
        ticker = _lookup_ticker(name, name_index)
        if ticker and ticker not in dsi_dict:
            try:
                dsi_dict[ticker] = float(dsi_val)
            except (TypeError, ValueError):
                continue
    return dsi_dict


def _parse_w_df(df_w) -> dict:
    """Ищет в DataFrame колонку с направлениями {вверх/вниз/рейндж}. Иначе {}."""
    result = {}
    if df_w is None or df_w.empty:
        return result

    direction_col = None
    for col in df_w.columns:
        vals = df_w[col].dropna().astype(str).str.lower().str.strip()
        if vals.isin(set(_W_ALIASES.keys())).any():
            direction_col = col
            break
    if direction_col is None:
        return result

    ticker_col = next(
        (c for c in df_w.columns if 'тикер' in str(c).lower() or 'ticker' in str(c).lower()),
        df_w.columns[0],
    )
    if ticker_col == direction_col:
        ticker_col = df_w.columns[1] if len(df_w.columns) > 1 else df_w.columns[0]

    for _, row in df_w.iterrows():
        t_raw = row[ticker_col]
        d_raw = row[direction_col]
        if pd.isna(t_raw) or pd.isna(d_raw):
            continue
        ticker = str(t_raw).strip().upper()
        if not _TICKER_RE.match(ticker) or ticker in {'ТИКЕР', 'TICKER'}:
            continue
        direction = str(d_raw).strip().lower()
        if direction in _W_ALIASES:
            result[ticker] = _W_ALIASES[direction]
    return result


def _parse_w_any(xls: pd.ExcelFile) -> dict:
    """Сначала лист 'W-формации' (если есть), иначе первый лист."""
    if 'W-формации' in xls.sheet_names:
        df_w = pd.read_excel(xls, sheet_name='W-формации', header=None)
        direction_idx = None
        for i in range(df_w.shape[1]):
            vals = df_w.iloc[:, i].dropna().astype(str).str.lower().str.strip()
            if vals.isin(set(_W_ALIASES.keys())).any():
                direction_idx = i
                break
        if direction_idx is None:
            return {}
        ticker_idx = 0 if direction_idx != 0 else 1
        result = {}
        for _, row in df_w.iterrows():
            t_raw = row.iloc[ticker_idx] if ticker_idx < len(row) else None
            d_raw = row.iloc[direction_idx] if direction_idx < len(row) else None
            if pd.isna(t_raw) or pd.isna(d_raw):
                continue
            ticker = str(t_raw).strip().upper()
            if not _TICKER_RE.match(ticker) or ticker in {'ТИКЕР', 'TICKER'}:
                continue
            direction = str(d_raw).strip().lower()
            if direction in _W_ALIASES:
                result[ticker] = _W_ALIASES[direction]
        return result

    df_w = pd.read_excel(xls, sheet_name=0)
    return _parse_w_df(df_w)


def _parse_portfolio(df_raw: pd.DataFrame, df_stocks: pd.DataFrame):
    """
    Читает файл портфеля и возвращает (positions, error).
    Из Excel используются ТОЛЬКО три колонки: Тикер, ТВХ, Лотов.
    Все остальные колонки игнорируются.
    """
    if df_raw is None or df_raw.empty:
        return None, "Файл пуст"

    # 1. Ищем строку заголовка по трём маркерам
    header_row = None
    for i in range(min(15, len(df_raw))):
        vals = [str(x).strip().lower() for x in df_raw.iloc[i].tolist()]
        has_ticker = any("тикер" in v or "ticker" in v for v in vals)
        has_price  = any("твх" in v or "средн" in v or "цена покупки" in v for v in vals)
        has_qty    = any("лотов" in v or "кол-во" in v or "количество" in v for v in vals)
        if has_ticker and (has_price or has_qty):
            header_row = i
            break

    if header_row is None:
        return None, "Не найдена строка заголовка. Ожидаются колонки «Тикер», «ТВХ», «Лотов»."

    headers = [str(x).strip() for x in df_raw.iloc[header_row].tolist()]
    data = df_raw.iloc[header_row + 1:].reset_index(drop=True)

    def find_col(patterns):
        for pat in patterns:
            for i, h in enumerate(headers):
                if pat in h.lower():
                    return i
        return None

    tcol = find_col(["тикер", "ticker", "secid"])
    vcol = find_col(["твх", "средняя цена", "цена покупки", "цена", "avg"])
    qcol = find_col(["лотов", "лоты", "кол-во лотов", "qty", "quantity"])

    if tcol is None:
        return None, "Не найдена колонка «Тикер»."
    if vcol is None:
        return None, "Не найдена колонка «ТВХ» / «Средняя цена»."
    if qcol is None:
        return None, "Не найдена колонка «Лотов»."

    valid = set(df_stocks["SECID"].tolist()) if df_stocks is not None and not df_stocks.empty else set()

    positions = []
    skipped = []
    for _, row in data.iterrows():
        ticker = str(row.iloc[tcol]).strip().upper()
        if not ticker or ticker in ("NAN", "NONE", "-"):
            continue
        if not _TICKER_RE.match(ticker):
            continue
        if valid and ticker not in valid:
            skipped.append(ticker)
            continue
        try:
            tvh = float(row.iloc[vcol])
            qty = int(float(row.iloc[qcol]))
        except (TypeError, ValueError):
            continue
        if tvh <= 0 or qty <= 0:
            continue
        positions.append({"ticker": ticker, "tvh": tvh, "qty": qty})

    if not positions:
        return None, "Не найдено ни одной валидной позиции (Тикер в ISS + ТВХ>0 + Лотов>0)."

    return positions, None


# ============================================================
# Сайдбар
# ============================================================
with st.sidebar:
    st.header("Настройки")
    st.text_input("Экстремум", value=G["extreme_date"], key="sb_extreme", on_change=_sync_extreme)
    st.number_input("Ставка ЦБ, %", value=float(G["cb_rate"]), step=0.25, format="%.2f", key="sb_cb", on_change=_sync, args=("sb_cb", "cb_rate"))
    st.number_input("Депозит, ₽", value=int(G["deposit"]), step=1000, key="sb_dep", on_change=_sync, args=("sb_dep", "deposit"))
    st.number_input("Резерв кэша, %", value=float(G["cash_reserve"]), step=1.0, key="sb_cash", on_change=_sync, args=("sb_cash", "cash_reserve"))

    st.divider()
    st.header("Импорт / Экспорт")

    # ---------- 1. W-формации ----------
    w_file = st.file_uploader(
        "Импорт W-формаций (Excel)", type=["xlsx", "xls"], key="upl_w",
    )
    if w_file is not None:
        _h = _file_hash(w_file)
        if st.session_state.get("_w_hash") != _h:
            try:
                xls = pd.ExcelFile(w_file)
                new_w = _parse_w_any(xls)
                if new_w:
                    state.set_global("w_formations", new_w)
                    st.session_state["_w_hash"] = _h
                    st.success(f"W-формации загружены: {len(new_w)} тикеров")
                    state.autosave()
                else:
                    st.error(
                        "Не найдены направления (вверх/вниз/рейндж). "
                        "W-формации не изменены."
                    )
            except Exception as e:
                st.error(f"Ошибка W: {e}")
        else:
            st.caption("✓ W-формации уже загружены")

    # ---------- 2. Источники (Арсагера + DSI) ----------
    sources_file = st.file_uploader(
        "Импорт Источников (Арсагера, DSI)", type=["xlsx", "xls"], key="upl_src",
    )
    if sources_file is not None:
        _h = _file_hash(sources_file)
        if st.session_state.get("_src_hash") != _h:
            try:
                xls = pd.ExcelFile(sources_file)

                ars_dict, name_index = {}, {}
                if 'Рейтинг арсагера' in xls.sheet_names:
                    df_ars = pd.read_excel(xls, sheet_name='Рейтинг арсагера', header=None)
                    ars_dict, name_index = _parse_arsagera(df_ars)

                dsi_dict = {}
                if 'ДОХОД DSI' in xls.sheet_names:
                    df_dsi = pd.read_excel(xls, sheet_name='ДОХОД DSI')
                    dsi_dict = _parse_dsi(df_dsi, name_index)

                if 'W-формации' in xls.sheet_names:
                    w_dict = _parse_w_any(xls)
                    if w_dict:
                        state.set_global("w_formations", w_dict)
                        st.info(f"Из Источников также загружены W-формации: {len(w_dict)}")

                fund_data = {
                    t: {
                        "ars_group": ars_dict.get(t, 0),
                        "dsi": dsi_dict.get(t, 0.0),
                    }
                    for t in set(ars_dict) | set(dsi_dict)
                }

                if not fund_data:
                    st.error(
                        f"Загружено 0 записей! Листы: {xls.sheet_names}. "
                        f"Арсагера={len(ars_dict)}, DSI={len(dsi_dict)}."
                    )
                else:
                    state.set_global("fundamental_data", fund_data)
                    st.session_state["_src_hash"] = _h
                    st.success(
                        f"Загружено {len(fund_data)} записей "
                        f"(Арсагера {len(ars_dict)} + DSI {len(dsi_dict)})"
                    )
                    st.caption(
                        f"LKOH → Арс={fund_data.get('LKOH', {}).get('ars_group')}, "
                        f"DSI={fund_data.get('LKOH', {}).get('dsi')}"
                    )
                    state.autosave()
            except Exception as e:
                st.error(f"Ошибка чтения источников: {e}")
        else:
            st.caption("✓ Источники уже загружены")

    # ---------- 3. Портфель ----------
    port_file = st.file_uploader(
        "Импорт Портфеля (Excel)", type=["xlsx", "xls"], key="upl_port",
    )
    if port_file is not None:
        _h = _file_hash(port_file)
        if st.session_state.get("_port_hash") != _h:
            try:
                df_port = pd.read_excel(port_file, header=None)
                positions, err = _parse_portfolio(df_port, df_stocks)
                if err:
                    st.error(f"Портфель: {err}")
                else:
                    fname = Path(port_file.name).stem
                    state.set_global("portfolio_positions", positions)
                    state.set_global("portfolio_name", fname)
                    st.session_state["_port_hash"] = _h
                    st.success(f"«{fname}» — {len(positions)} позиций")
                    state.autosave()
            except Exception as e:
                st.error(f"Ошибка чтения портфеля: {e}")
        else:
            st.caption("✓ Портфель уже загружен")

    # ---------- JSON ----------
    if st.button("Подготовить экспорт JSON"):
        st.session_state["_export_blob"] = storage.dumps(S)
    blob = st.session_state.get("_export_blob")
    if blob:
        st.download_button(
            "Скачать JSON",
            data=blob,
            file_name=f"backup_{datetime.now().strftime('%d_%m_%y')}.json",
            mime="application/json",
        )

    json_file = st.file_uploader("Импорт JSON (полный бэкап)", type=["json"], key="upl_json")
    if json_file and st.button("Применить бэкап"):
        parsed = storage.loads(json_file.getvalue().decode("utf-8"))
        if parsed:
            state.replace_state(parsed)
            st.success("Загружено!")
            st.rerun()

    # ---------- Сброс импортов ----------
    if st.button("🗑 Сбросить импорты"):
        for k in ("_w_hash", "_src_hash", "_port_hash"):
            st.session_state.pop(k, None)
        state.set_global("fundamental_data", {})
        state.set_global("portfolio_positions", [])
        state.set_global("portfolio_name", "Портфель")
        from core.config import DEFAULT_W_FORMATIONS
        state.set_global("w_formations", DEFAULT_W_FORMATIONS)
        state.autosave(force=True)
        st.success("Импорты сброшены.")
        st.rerun()

    # ---------- Диагностика ----------
    with st.expander("🔍 Диагностика (state)", expanded=False):
        fd = state.g("fundamental_data", {})
        wf = state.g("w_formations", {})
        pf = state.g("portfolio_positions", [])
        st.caption(f"**fundamental_data**: {len(fd)} записей")
        if fd:
            st.json({k: fd[k] for k in list(fd)[:5]})
        else:
            st.warning("fundamental_data ПУСТ → Арсагера=0, DSI=0")
        st.caption(f"**w_formations**: {len(wf)} записей | LKOH = {wf.get('LKOH', '—')}")
        st.caption(f"**portfolio_positions**: {len(pf)} позиций")


# ============================================================
# Основные вкладки
# ============================================================
tab_market, tab_rating, tab_indices, tab_portfolio, tab_calc = st.tabs([
    "Обзор", "Рейтинг", "Индексы", "Портфель", "Калькулятор"
])

with tab_market:
    try:
        render_main_tab(df_stocks=df_stocks, deposit=G["deposit"])
    except Exception as e:
        st.error(f"Ошибка в 'Обзоре': {e}")

with tab_rating:
    try:
        render_rating()
    except Exception as e:
        st.error(f"Ошибка в 'Рейтинге': {e}")

with tab_indices:
    try:
        render_indices()
    except Exception as e:
        st.error(f"Ошибка в 'Индексах': {e}")

with tab_portfolio:
    try:
        render_portfolio(df_stocks=df_stocks)
    except Exception as e:
        st.error(f"Ошибка в 'Портфеле': {e}")

with tab_calc:
    active_tickers = G.get("active_tickers", [])
    if not active_tickers:
        st.info("Выберите тикер на вкладке 'Обзор'.")
    else:
        active = seg("Инструмент", active_tickers, key="plan_ticker", default=active_tickers[0])
        if not active or active not in active_tickers:
            active = active_tickers[0]
        try:
            render_trade_planner(active, df_stocks)
        except Exception as e:
            st.error(f"Ошибка в 'Калькуляторе': {e}")

state.autosave()
