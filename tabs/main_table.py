from __future__ import annotations
import streamlit as st
import pandas as pd
from core import state
from core.config import TREND_VALUES

def render_main_tab(df_stocks: pd.DataFrame, deposit: float):
    st.subheader("Обзор рынка акций")
    if df_stocks is None or df_stocks.empty:
        st.warning("Нет данных с MOEX ISS.")
        return

    # === 1. ВЫБОР ИНСТРУМЕНТОВ ===
    st.markdown("#### Выбор инструментов (Watchlist)")
    st.info("Отметьте галочками акции, чтобы добавить их в калькулятор и рейтинг.")
    
    # Готовим таблицу для отображения
    df_display = df_stocks[["SECID", "SHORTNAME", "PRICE", "LASTCHANGEPRCNT", "LOT_VALUE", "LISTLEVEL"]].copy()
    
    # Добавляем колонку выбора (галочки) на основе текущего стейта
    active = state.g("active_tickers", [])
    df_display.insert(0, "Выбрать", df_display["SECID"].isin(active))
    
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=400,
        column_config={
            "Выбрать": st.column_config.CheckboxColumn("В портфель", default=False),
            "SECID": "Тикер",
            "SHORTNAME": "Наименование",
            "PRICE": st.column_config.NumberColumn("Цена", format="%.2f ₽"),
            "LASTCHANGEPRCNT": st.column_config.NumberColumn("Изм. %", format="%.2f%%"),
            "LOT_VALUE": st.column_config.NumberColumn("Стоимость лота", format="%.2f ₽"),
            "LISTLEVEL": "Ур. листинга"
        },
        disabled=["SECID", "SHORTNAME", "PRICE", "LASTCHANGEPRCNT", "LOT_VALUE", "LISTLEVEL"]
    )

    # Синхронизируем выбор с глобальным состоянием
    selected = edited_df[edited_df["Выбрать"]]["SECID"].tolist()
    if selected != active:
        state.set_global("active_tickers", selected)
        state.autosave()
        st.rerun()

    # === 2. НАСТРОЙКА ТРЕНДОВ ===
    st.markdown("#### Настройка параметров рынка")
    if not active:
        st.caption("Выберите хотя бы одну акцию выше.")
        return
        
    rows = []
    for t in active:
        m = state.ticker(t)["market"]
        rows.append({
            "Тикер": t, 
            "Тренд": m.get("trend", "вверх"), 
            "Волна": m.get("wave", "вверх"), 
            "Тенденция": m.get("tendency", "вверх")
        })
    
    t_df = pd.DataFrame(rows)
    t_edited = st.data_editor(
        t_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Тренд": st.column_config.SelectboxColumn(options=TREND_VALUES, required=True),
            "Волна": st.column_config.SelectboxColumn(options=TREND_VALUES, required=True),
            "Тенденция": st.column_config.SelectboxColumn(options=TREND_VALUES, required=True)
        },
        disabled=["Тикер"]
    )
    
    # Сохраняем изменения трендов
    for _, r in t_edited.iterrows():
        state.ticker(r["Тикер"])["market"].update({
            "trend": r["Тренд"], 
            "wave": r["Волна"], 
            "tendency": r["Тенденция"]
        })
    state.autosave()
