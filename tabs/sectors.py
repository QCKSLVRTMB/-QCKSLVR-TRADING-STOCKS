import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks
from core.ranking import calc_ranking

def render_sectors():
    st.subheader("Распределение портфеля по секторам")
    df_stocks = fetch_moex_stocks()
    if df_stocks.empty: return

    deposit = state.g("deposit")
    cash_reserve = state.g("cash_reserve")
    available = deposit * (1 - cash_reserve / 100)
    
    st.info(f"Депозит: {deposit:,.2f} ₽ | Резерв: {cash_reserve}% | Доступно: **{available:,.2f} ₽**")
    
    # В реальном коде здесь будет разбивка по секторам и расчет долей
    # Заглушка для интерфейса:
    st.markdown("#### Настройка весов секторов")
    st.write("Функционал ручного и авто-распределения весов будет добавлен здесь.")
