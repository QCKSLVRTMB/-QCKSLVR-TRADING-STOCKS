from __future__ import annotations
import streamlit as st
from datetime import datetime
import pandas as pd
import re
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
    st.text_input("Экстремум", value=G["extreme_date"], key="sb_extreme", on_change=_sync_extreme)
    st.number_input("Ставка ЦБ, %", value=float(G["cb_rate"]), step=0.25, format="%.2f", key="sb_cb", on_change=_sync, args=("sb_cb", "cb_rate"))
    st.number_input("Депозит, ₽", value=int(G["deposit"]), step=1000, key="sb_dep", on_change=_sync, args=("sb_dep", "deposit"))
    st.number_input("Резерв кэша, %", value=float(G["cash_reserve"]), step=1.0, key="sb_cash", on_change=_sync, args=("sb_cash", "cash_reserve"))

    st.divider()
    st.header("Импорт / Экспорт")
    
    # 1. Импорт W-формаций (Excel)
    w_file = st.file_uploader("Импорт W-формаций (Excel)", type=["xlsx", "xls"])
    if w_file:
        try:
            df_w = pd.read_excel(w_file)
            ticker_col = next((c for c in df_w.columns if 'Тикер' in str(c) or 'ticker' in str(c).lower()), df_w.columns[0])
            form_col = next((c for c in df_w.columns if 'Формация' in str(c) or 'формация' in str(c).lower()), df_w.columns[1])
            new_w = dict(zip(df_w[ticker_col].astype(str).str.strip().str.upper(), df_w[form_col]))
            state.set_global("w_formations", new_w)
            st.success("W-формации загружены!")
            state.autosave()
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка: {e}")

    # 2. Импорт Источников (Арсагера + DSI)
    sources_file = st.file_uploader("Импорт Источников (Арсагера, DSI)", type=["xlsx", "xls"])
    if sources_file:
        try:
            xls = pd.ExcelFile(sources_file)
            
            # Парсинг Арсагеры (горизонтальные блоки)
            ars_dict = {}
            name_to_ticker = {}
            if 'Рейтинг арсагера' in xls.sheet_names:
                df_ars = pd.read_excel(xls, sheet_name='Рейтинг арсагера', header=None)
                # Блоки начинаются с колонок 0, 5, 10, 15
                for start_col in [0, 5, 10, 15]:
                    for i in range(2, len(df_ars)): # Данные со 3-й строки (индекс 2)
                        ticker = df_ars.iloc[i, start_col]
                        name = df_ars.iloc[i, start_col + 1]
                        rank = df_ars.iloc[i, start_col + 3]
                        
                        if pd.notna(ticker) and pd.notna(rank):
                            t_str = str(ticker).strip().upper()
                            try:
                                ars_dict[t_str] = int(rank)
                            except ValueError:
                                pass
                        if pd.notna(name) and pd.notna(ticker):
                            name_to_ticker[str(name).strip()] = str(ticker).strip().upper()

            # Парсинг DSI
            dsi_dict = {}
            if 'ДОХОД DSI' in xls.sheet_names:
                df_dsi = pd.read_excel(xls, sheet_name='ДОХОД DSI')
                # Ищем нужные колонки
                col_name = next((c for c in df_dsi.columns if 'Акция' in str(c)), None)
                col_dsi = next((c for c in df_dsi.columns if 'DSI' in str(c)), None)
                
                if col_name and col_dsi:
                    for _, row in df_dsi.iterrows():
                        name = str(row[col_name]).strip()
                        dsi_val = row[col_dsi]
                        if pd.notna(dsi_val):
                            ticker = name_to_ticker.get(name)
                            if ticker:
                                dsi_dict[ticker] = float(dsi_val)
            
            # Собираем все вместе
            fund_data = {}
            for t in set(list(ars_dict.keys()) + list(dsi_dict.keys())):
                fund_data[t] = {
                    "ars_group": ars_dict.get(t, 0),
                    "dsi": dsi_dict.get(t, 0.0)
                }
            
            state.set_global("fundamental_data", fund_data)
            st.success(f"Загружено {len(fund_data)} записей (Арсагера + DSI)")
            state.autosave()
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка чтения источников: {e}")

    # 3. Портфель (Excel)
    port_file = st.file_uploader("Импорт Портфеля (Excel)", type=["xlsx", "xls"])
    if port_file:
        try:
            df_port = pd.read_excel(port_file)
            state.set_global("portfolio_data", df_port.to_dict(orient="records"))
            st.success("Портфель загружен!")
            state.autosave()
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка: {e}")

    if st.button("Подготовить экспорт JSON"):
        st.session_state["_export_blob"] = storage.dumps(S)
    blob = st.session_state.get("_export_blob")
    if blob:
        st.download_button("Скачать JSON", data=blob, file_name=f"backup_{datetime.now().strftime('%d_%m_%y')}.json", mime="application/json")

    json_file = st.file_uploader("Импорт JSON (полный бэкап)", type=["json"])
    if json_file and st.button("Применить бэкап"):
        parsed = storage.loads(json_file.getvalue().decode("utf-8"))
        if parsed:
            state.replace_state(parsed)
            st.success("Загружено!"); st.rerun()

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
