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
    df["№"] = df.index + 1

    # Формируем датафрейм для отображения в строго заданном порядке
    display_df = pd.DataFrame({
        "№": df["№"],
        "Название": df["SHORTNAME"],
        "Тикер": df["SECID"],
        "Вид актива": df.apply(lambda r: get_asset_color(r["div_yield"], cb_rate, r["rel_strength"]), axis=1),
        "Формация": df["w_form"],
        "В составе индекса": df["in_index"],
        "Сила актива": df["rel_strength"],
        "Дивидендная доходность (по рынку)": df["div_yield"],
        "Тип листинга": df["LISTLEVEL"],
        "Сумма баллов": df["total_score"],
        "Рекомендуемая цена": df["recommended_price"]
    })

    # Функция стилизации (заливка цветом)
    def apply_styles(row):
        styles = [""] * len(row)
        
        # Формация (индекс 4)
        w = row["Формация"]
        if w == "вверх": styles[4] = "background-color: #4CAF50; color: #4CAF50;"
        elif w == "рейндж": styles[4] = "background-color: #2196F3; color: #2196F3;"
        elif w == "вниз": styles[4] = "background-color: #F44336; color: #F44336;"

        # В составе индекса (индекс 5)
        if row["В составе индекса"]: styles[5] = "background-color: #4CAF50; color: #4CAF50;"
        else: styles[5] = "background-color: #F44336; color: #F44336;"

        # Сила актива (индекс 6)
        if row["Сила актива"] > 0: styles[6] = "background-color: #4CAF50; color: #4CAF50;"
        else: styles[6] = "background-color: #F44336; color: #F44336;"

        # Вид актива (индекс 3)
        color = row["Вид актива"]
        if color == "green": styles[3] = "background-color: #4CAF50; color: #4CAF50;"
        elif color == "yellow": styles[3] = "background-color: #FFEB3B; color: #FFEB3B;"
        elif color == "orange": styles[3] = "background-color: #FF9800; color: #FF9800;"
        elif color == "red": styles[3] = "background-color: #F44336; color: #F44336;"

        return styles

    # Применяем стили и форматирование (скрываем текст в цветных ячейках)
    styled_df = (
        display_df.style
        .apply(apply_styles, axis=1)
        .format({
            "Вид актива": lambda x: "",
            "Формация": lambda x: "",
            "В составе индекса": lambda x: "",
            "Сила актива": lambda x: "",
            "Дивидендная доходность (по рынку)": "{:.2f}%",
            "Тип листинга": "{:.0f}",
            "Сумма баллов": "{:.0f}",
            "Рекомендуемая цена": "{:.2f} ₽",
            "№": "{:.0f}"
        })
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Вид актива": st.column_config.TextColumn(width="small"),
            "Формация": st.column_config.TextColumn(width="small"),
            "В составе индекса": st.column_config.TextColumn(width="small"),
            "Сила актива": st.column_config.TextColumn(width="small"),
            "Дивидендная доходность (по рынку)": st.column_config.TextColumn(width="medium"),
            "Рекомендуемая цена": st.column_config.TextColumn(width="medium"),
        }
    )
