import streamlit as st
import pandas as pd
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking, get_asset_color
from core import state

def render_rating():
    st.subheader("Рейтинг акций")
    df_stocks = fetch_moex_stocks()
    df_indices = fetch_moex_indices()
    
    if df_stocks.empty or df_indices.empty:
        st.warning("Нет данных MOEX.")
        return

    # Берем топ-30 по объему торгов, чтобы гарантировать быструю загрузку
    if "VALTODAY" in df_stocks.columns:
        df_stocks = df_stocks[df_stocks["VALTODAY"] > 0].sort_values("VALTODAY", ascending=False).head(30)

    extreme_date = state.g("extreme_date")
    
    with st.spinner("Расчет рейтинга..."):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID']=='IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0.0

        w_forms = state.g("w_formations")
        cb_rate = state.g("cb_rate")
        
        df = calc_ranking(df_stocks, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr)
    
    df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
    df["№"] = df.index + 1

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

    def apply_styles(row):
        styles = [""] * len(row)
        w = row["Формация"]
        if w == "вверх": styles[4] = "background-color: #4CAF50; color: #4CAF50;"
        elif w == "рейндж": styles[4] = "background-color: #2196F3; color: #2196F3;"
        elif w == "вниз": styles[4] = "background-color: #F44336; color: #F44336;"
        
        if row["В составе индекса"]: styles[5] = "background-color: #4CAF50; color: #4CAF50;"
        else: styles[5] = "background-color: #F44336; color: #F44336;"
        
        if row["Сила актива"] > 0: styles[6] = "background-color: #4CAF50; color: #4CAF50;"
        else: styles[6] = "background-color: #F44336; color: #F44336;"
        
        color = row["Вид актива"]
        if color == "green": styles[3] = "background-color: #4CAF50; color: #4CAF50;"
        elif color == "yellow": styles[3] = "background-color: #FFEB3B; color: #FFEB3B;"
        elif color == "orange": styles[3] = "background-color: #FF9800; color: #FF9800;"
        elif color == "red": styles[3] = "background-color: #F44336; color: #F44336;"
        
        return styles

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

    st.dataframe(styled_df, use_container_width=True, hide_index=True)
