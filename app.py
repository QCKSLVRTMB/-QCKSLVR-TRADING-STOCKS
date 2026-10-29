from __future__ import annotations
import streamlit as st
from datetime import datetime
import pandas as pd
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

    st.divider()
    st.header("Импорт / Экспорт")
    
    # 1. Загрузка W-формаций
    w_file = st.file_uploader("1. W-формации (Excel)", type=["xlsx", "xls"])
    if w_file:
        try:
            df_w = pd.read_excel(w_file)
            if len(df_w.columns) >= 2:
                new_w = dict(zip(df_w.iloc[:, 0].astype(str).str.upper(), df_w.iloc[:, 1]))
                state.set_global("w_formations", new_w)
                st.success("W-формации обновлены!")
                state.autosave()
                st.rerun()
        except Exception as e:
            st.error(f"Ошибка W: {e}")

    # 2. Загрузка DSI и Арсагеры
    fund_file = st.file_uploader("2. DSI и Арсагера (Excel)", type=["xlsx", "xls"])
    if fund_file:
        try:
            df_fund = pd.read_excel(fund_file)
            if len(df_fund.columns) >= 3:
                new_fund = {}
                for _, row in df_fund.iterrows():
                    ticker = str(row.iloc[0]).strip().upper()
                    ars = int(row.iloc[1]) if pd.notna(row.iloc[1]) else 0
                    dsi = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0
                    new_fund[ticker] = {"ars_group": ars, "dsi": dsi}
                state.set_global("fundamental_data", new_fund)
                st.success("DSI и Арсагера обновлены!")
                state.autosave()
                st.rerun()
        except Exception as e:
            st.error(f"Ошибка DSI: {e}")

    # 3. Загрузка Портфеля
    port_file = st.file_uploader("3. Портфель (Excel)", type=["xlsx", "xls"])
    if port_file:
        try:
            df_port = pd.read_excel(port_file)
            state.set_global("portfolio_data", df_port.to_dict(orient="records"))
            st.success("Портфель загружен!")
            state.autosave()
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка портфеля: {e}")

    st.divider()
    
    # Экспорт JSON
    if st.button("Подготовить экспорт JSON", use_container_width=True):
        st.session_state["_export_blob"] = storage.dumps(S)
    blob = st.session_state.get("_export_blob")
    if blob:
        st.download_button("Скачать JSON", data=blob, file_name=f"backup_{datetime.now().strftime('%d_%m_%y')}.json", mime="application/json", use_container_width=True)

    # Импорт JSON
    json_file = st.file_uploader("Импорт JSON (бэкап)", type=["json"])
    if json_file and st.button("Применить бэкап", use_container_width=True):
        parsed_json = storage.loads(json_file.getvalue().decode("utf-8"))
        if parsed_json:
            state.replace_state(parsed_json)
            st.success("Данные восстановлены!"); st.rerun()

df_stocks = fetch_moex_stocks()

tab_market, tab_rating, tab_indices, tab_portfolio, tab_calc = st.tabs([
    "Обзор", "Рейтинг", "Индексы", "Портфель", "Калькулятор"
])

with tab_market:
    try: render_main_tab(df_stocks=df_stocks, deposit=G["deposit"])
    except Exception as e: st.error(f"Ошибка в 'Обзоре': {e}")

with tab_rating:
    try: render_rating()
    except Exception as e: st.error(f"Ошибка в 'Рейтинге': {e}")

with tab_indices:
    try: render_indices()
    except Exception as e: st.error(f"Ошибка в 'Индексах': {e}")

with tab_portfolio:
    try: render_portfolio(df_stocks=df_stocks)
    except Exception as e: st.error(f"Ошибка в 'Портфеле': {e}")

with tab_calc:
    active_tickers = G.get("active_tickers", [])
    if not active_tickers:
        st.info("Выберите тикер на вкладке 'Обзор'.")
    else:
        active = seg("Инструмент", active_tickers, key="plan_ticker", default=active_tickers[0])
        if not active or active not in active_tickers: active = active_tickers[0]
        try: render_trade_planner(active, df_stocks)
        except Exception as e: st.error(f"Ошибка в 'Калькуляторе': {e}")

state.autosave()
