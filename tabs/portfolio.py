import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks, fetch_dividends_smartlab

def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")
    
    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("Загрузите файл портфеля в боковом меню для отображения таблицы.")
        return

    df_port = pd.DataFrame(port_data)
    
    # Если файл не загружен или пуст
    if df_port.empty:
        st.warning("Данные портфеля пусты.")
        return

    # Обогащаем данными из ISS и Smart-Lab
    # (Здесь мы просто выводим таблицу, расчеты добавим позже по вашим формулам)
    
    # Для начала выведем просто те колонки, которые есть в Excel, 
    # чтобы вы могли видеть структуру.
    
    st.dataframe(df_port, use_container_width=True)
    
    st.caption("Таблица отображает данные из загруженного файла. Расчеты и интеграция с Smart-Lab будут добавлены на следующем шаге.")
