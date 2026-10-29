import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks

def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")
    
    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("Загрузите файл портфеля в боковом меню для отображения таблицы.")
        return

    df_port = pd.DataFrame(port_data)
    
    if df_port.empty:
        st.warning("Данные портфеля пусты.")
        return

    st.dataframe(df_port, use_container_width=True)
    st.caption("Таблица отображает данные из загруженного файла. Расчеты действий и ребалансировки будут добавлены на следующем шаге.")
