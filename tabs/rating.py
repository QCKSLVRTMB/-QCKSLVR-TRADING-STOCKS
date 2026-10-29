import streamlit as st
import pandas as pd
from core.market import fetch_moex_stocks
from core.ranking import calc_ranking
from core import state

def render_rating():
    st.subheader("Рейтинг акций")
    df_stocks = fetch_moex_stocks()
    if df_stocks.empty:
        st.warning("Нет данных MOEX.")
        return
        
    w_forms = state.g("w_formations")
    cb_rate = state.g("cb_rate")
    
    df = calc_ranking(df_stocks, w_forms, cb_rate)
    df = df.sort_values("total_score", ascending=False)
    
    st.dataframe(
        df[["SECID", "SHORTNAME", "PRICE", "w_form", "score_w", "score_div", "score_list", "total_score"]],
        use_container_width=True, hide_index=True,
        column_config={
            "SECID": "Тикер", "SHORTNAME": "Название", "PRICE": "Цена",
            "w_form": "W-формация", "score_w": "Баллы W", 
            "score_div": "Баллы Див", "score_list": "Баллы Листинг",
            "total_score": st.column_config.ProgressColumn("Итог", min_value=0, max_value=600, format="%d")
        }
    )
