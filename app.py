from __future__ import annotations
import streamlit as st
from datetime import datetime
from core import state
from core.config import APP_TITLE
from core.market import fetch_moex_stocks
from tabs.main_table import render_main_tab
from tabs.indices import render_indices
from tabs.rating import render_rating
from tabs.sectors import render_sectors
from tabs.trade_planner import render_trade_planner
from ui.theme import inject_css, seg

st.set_page_config(page_title=APP_TITLE, layout="wide", initial_sidebar_state="expanded")
inject_css()

S = state.get_state()
G = S["global"]

def _sync(key, gkey):
    state.set_global(gkey, st.session_state[key])

def _sync_extreme():
    val = st.session_state.sb_extreme
    try:
        datetime.strptime(val, "%d.%m.%Y")
        state.set_global("extreme_date", val)
    except ValueError:
        st.error("Неверный формат даты. Используйте DD.MM.YYYY")

with st.sidebar:
    st.header("Настройки")
    st.text_input("Экстремум", value=G["extreme_date"], key="sb_extreme", on_change=_sync_extreme, help="Формат: DD.MM.YYYY")
    st.number_input("Ставка ЦБ, %", value=float(G["cb_rate"]), step=0.25, format="%.2f", key="sb_cb", on_change=_sync, args=("sb_cb", "cb_rate"))
    st.number_input("Депозит, ₽", value=int(G["deposit"]), step=1000, key="sb_dep", on_change=_sync, args=("sb_dep", "deposit"))
    st.number_input("Резерв кэша, %", value=float(G["cash_reserve"]), step=1.0, key="sb_cash", on_change=_sync, args=("sb_cash", "cash_reserve"))

df_stocks = fetch_moex_stocks()

tab_market, tab_rating, tab_indices, tab_sectors, tab_calc = st.tabs([
    "Обзор", "Рейтинг", "Индексы", "Секторы", "Калькулятор"
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

with tab_sectors:
    try:
        render_sectors()
    except Exception as e:
        st.error(f"Ошибка в 'Секторах': {e}")

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
