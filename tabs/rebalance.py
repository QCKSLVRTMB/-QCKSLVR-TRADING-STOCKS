from __future__ import annotations
import streamlit as st
import pandas as pd
import math
from core import state
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking
from core.calc import get_instrument

def _fmt2(x):
    try:
        return f"{float(x):,.2f}".replace(',', ' ').replace('.', ',')
    except (ValueError, TypeError):
        return str(x)

DEFAULT_SECTORS = [
    "Нефтегаз", "Финансовый", "Металлы и добыча", "Энергетика",
    "Телекомы", "Потребительский", "Химия", "Инновации",
    "Транспорт", "ИТ", "Строительство", "Разное",
]

def render_rebalance():
    st.subheader("Ребалансировка портфеля")
    st.markdown("Распределение целевого капитала по секторам и активам на основе их рейтинговых баллов.")
    df_stocks = fetch_moex_stocks()
    df_indices = fetch_moex_indices()
    if df_stocks.empty:
        st.warning("Нет данных MOEX.")
        return
    df_stocks = df_stocks[df_stocks["PRICE"] > 0].copy()
    extreme_date = state.g("extreme_date")
    positions = state.g("portfolio_data", [])
    
    with st.spinner("Расчет баллов акций..."):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices["SECID"] == "IMOEX"]
        imoex_curr = float(imoex_row["CURRENTVALUE"].values[0]) if not
