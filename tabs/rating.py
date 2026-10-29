import streamlit as st
import pandas as pd
from core.market import fetch_moex_stocks
from core.ranking import calc_ranking, get_asset_color
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
    
    # Сортировка по убыванию суммы баллов
    df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
    
    # Функция для раскраски колонки "SECID"
    def style_ticker(row):
        color = get_asset_color(row["div_yield"], cb_rate, row["rel_strength"])
        color_map = {
            "green": "background-color: #4CAF50; color: white;",
            "yellow": "background-color: #FFEB3B; color: black;",
            "orange": "background-color: #FF9800; color: black;",
            "red": "background-color: #F44336; color: white;"
        }
        # Применяем стиль только к колонке SECID (первая колонка)
        return [color_map.get(color, "")] + [""] * (len(row) - 1)

    # Форматируем таблицу и применяем стили
    styled_df = (
        df[["SECID", "SHORTNAME", "PRICE", "w_form", "score_w", "div_yield", "score_div", "score_list", "total_score"]]
        .style
        .apply(style_ticker, axis=1)
        .format({
            "PRICE": "{:.2f} ₽",
            "div_yield": "{:.2f}%",
            "total_score": "{:.0f}"
        })
    )
    
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        # height=None УДАЛЕН, чтобы избежать ошибки StreamlitInvalidHeightError
        column_config={
            "SECID": "Тикер", 
            "SHORTNAME": "Название", 
            "PRICE": "Цена",
            "w_form": "W-формация", 
            "score_w": "Баллы W", 
            "div_yield": "Див. доходность",
            "score_div": "Баллы Див", 
            "score_list": "Баллы Листинг",
            "total_score": "Итоговый балл"
        }
    )
