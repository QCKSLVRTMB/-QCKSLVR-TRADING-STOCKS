import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking

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

    with st.spinner("Расчет баллов акций..."):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID'] == 'IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0.0
        
        w_forms = state.g("w_formations")
        cb_rate = state.g("cb_rate")
        
        df_ranked = calc_ranking(df_stocks, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr)
        score_map = dict(zip(df_ranked["SECID"], df_ranked["total_score"]))
        name_map = dict(zip(df_ranked["SECID"], df_ranked["SHORTNAME"]))

    st.markdown("### 1. Настройка секторов")
    
    if "rebal_sectors" not in st.session_state:
        st.session_state["rebal_sectors"] = pd.DataFrame([
            {"Сектор": "Нефтегаз", "Доля, %": 35},
            {"Сектор": "Финансовый", "Доля, %": 25},
            {"Сектор": "Металлы и добыча", "Доля, %": 30},
            {"Сектор": "Разное", "Доля, %": 10},
        ])

    edited_sectors = st.data_editor(
        st.session_state["rebal_sectors"],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Сектор": st.column_config.TextColumn("Название сектора", required=True),
            "Доля, %": st.column_config.NumberColumn("Целевая доля, %", min_value=0, max_value=100, step=1, format="%d%%")
        }
    )
    st.session_state["rebal_sectors"] = edited_sectors
    
    total_pct = edited_sectors["Доля, %"].sum()
    if total_pct != 100:
        st.warning(f"⚠️ Сумма долей секторов равна {total_pct}%. Рекомендуется, чтобы сумма была 100%.")
    
    deposit = state.g("deposit", 100000)
    st.info(f"Общий депозит: **{deposit:,.2f} ₽**".replace(",", " "))

    st.markdown("### 2. Выбор активов (тикеров)")
    st.caption("Введите тикеры для каждого сектора. Баллы подтянутся автоматически из вкладки «Рейтинг».")

    all_tickers = sorted(df_stocks["SECID"].unique().tolist())
    
    if "rebal_tickers" not in st.session_state:
        st.session_state["rebal_tickers"] = {}

    for _, row in edited_sectors.iterrows():
        sector = row["Сектор"]
        pct = row["Доля, %"]
        
        if not sector: continue
            
        st.markdown(f"**{sector}** (Бюджет: {(deposit * pct / 100):,.0f} ₽)".replace(",", " "))
        
        default_tickers = st.session_state["rebal_tickers"].get(sector, [])
        selected = st.multiselect(
            f"Активы в секторе «{sector}»",
            options=all_tickers,
            default=default_tickers,
            key=f"tags_{sector}",
            label_visibility="collapsed"
        )
        st.session_state["rebal_tickers"][sector] = selected

    st.markdown("### 3. Итоговая таблица ребалансировки")
    
    table_rows = []
    
    for _, row in edited_sectors.iterrows():
        sector = row["Сектор"]
        pct = row["Доля, %"]
        if not sector: continue
            
        tickers = st.session_state["rebal_tickers"].get(sector, [])
        if not tickers: continue
            
        sector_budget = deposit * (pct / 100)
        sector_scores = {t: score_map.get(t, 0) for t in tickers}
        total_sector_score = sum(sector_scores.values())
        
        for t in tickers:
            score = sector_scores[t]
            
            if total_sector_score > 0:
                planned_amount = sector_budget * (score / total_sector_score)
                share_in_sector = (score / total_sector_score) * 100
            else:
                planned_amount = sector_budget / len(tickers)
                share_in_sector = 100 / len(tickers)
                
            share_in_portfolio = (planned_amount / deposit) * 100 if deposit > 0 else 0
            
            table_rows.append({
                "Сектор": sector,
                "Тикер": t,
                "Название": name_map.get(t, t),
                "Балл": score,
                "Планируемая сумма, ₽": planned_amount,
                "Доля в секторе, %": share_in_sector,
                "Доля в портфеле, %": share_in_portfolio,
            })

    if not table_rows:
        st.info("Добавьте тикеры в секторы, чтобы увидеть расчет.")
        return

    df_result = pd.DataFrame(table_rows)
    
    def style_row(row):
        styles = [""] * len(row)
        if row["Балл"] == 0:
            styles[3] = "background-color: #F44336; color: white;"
        else:
            styles[3] = "background-color: #4CAF50; color: white;"
        return styles

    styled_df = (
        df_result.style
        .apply(style_row, axis=1)
        .format({
            "Балл": "{:.0f}",
            "Планируемая сумма, ₽": "{:,.0f}",
            "Доля в секторе, %": "{:.2f}%",
            "Доля в портфеле, %": "{:.2f}%",
        })
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=40 + 35 * len(df_result) + 6
    )
    
    total_planned = df_result["Планируемая сумма, ₽"].sum()
    st.markdown(f"**Итого распределено:** {total_planned:,.0f} ₽ из {deposit:,.0f} ₽".replace(",", " "))
