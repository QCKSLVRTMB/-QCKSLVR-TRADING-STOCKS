import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking
from core.calc import get_instrument

DEFAULT_SECTORS = [
    "Нефтегаз", "Финансовый", "Металлы и добыча", "Энергетика", 
    "Телекомы", "Потребительский", "Химия", "Инновации", 
    "Транспорт", "ИТ", "Строительство", "Разное"
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

    with st.spinner("Расчет баллов акций..."):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID'] == 'IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0.0
        
        w_forms = state.g("w_formations")
        cb_rate = state.g("cb_rate")
        
        df_ranked = calc_ranking(df_stocks, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr)
        score_map = dict(zip(df_ranked["SECID"], df_ranked["total_score"]))
        name_map = dict(zip(df_ranked["SECID"], df_ranked["SHORTNAME"]))

    positions = state.g("portfolio_data", [])
    cash = state.g("portfolio_cash", 0.0)
    
    stocks_value = 0.0
    for p in positions:
        inst = get_instrument(p["Тикер"], df_stocks)
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        stocks_value += p["ТВХ"] * p["Лотов"] * lot_size

    total_portfolio_value = stocks_value + cash
    
    st.markdown("### 1. Настройка секторов")
    
    # Справочная информация
    if "rebal_sectors" in st.session_state:
        current_df = st.session_state["rebal_sectors"]
        active = [f"{row['Сектор']} - {row['Доля, %']:.0f}%" for _, row in current_df.iterrows() if row['Доля, %'] > 0]
        if active:
            st.markdown(f"**Текущее распределение:** {', '.join(active)}")
            
    st.info(
        f"Стоимость акций (база для распределения): {stocks_value:.2f} ₽ | "
        f"Кеш: {cash:.2f} ₽ | "
        f"Всего портфель: {total_portfolio_value:.2f} ₽"
    )

    if "rebal_sectors" not in st.session_state:
        st.session_state["rebal_sectors"] = pd.DataFrame([
            {"Сектор": s, "Доля, %": 0.0} for s in DEFAULT_SECTORS
        ])

    edited_sectors = st.data_editor(
        st.session_state["rebal_sectors"],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Сектор": st.column_config.TextColumn("Название сектора", required=True),
            "Доля, %": st.column_config.NumberColumn("Целевая доля, %", min_value=0.0, max_value=100.0, step=1.0, format="%.1f%%")
        }
    )
    st.session_state["rebal_sectors"] = edited_sectors
    
    total_pct = edited_sectors["Доля, %"].sum()
    if total_pct > 100.0:
        st.markdown(
            f"<div style='background-color: #ffcccc; padding: 10px; border-radius: 5px; color: red;'>"
            f"Ошибка: Сумма долей секторов равна {total_pct:.1f}%. Сумма не должна превышать 100%.</div>", 
            unsafe_allow_html=True
        )

    st.markdown("### 2. Выбор активов (тикеров)")
    st.caption("Тикеры подтягиваются автоматически на основе секторов из загруженного портфеля.")

    all_tickers = sorted(df_stocks["SECID"].unique().tolist())
    
    if "rebal_tickers" not in st.session_state:
        st.session_state["rebal_tickers"] = {}
        
    if not any(st.session_state["rebal_tickers"].values()):
        for p in positions:
            sec = p.get("Сектор", "Разное")
            if sec not in st.session_state["rebal_tickers"]:
                st.session_state["rebal_tickers"][sec] = []
            if p["Тикер"] not in st.session_state["rebal_tickers"][sec]:
                st.session_state["rebal_tickers"][sec].append(p["Тикер"])

    for _, row in edited_sectors.iterrows():
        sector = row["Сектор"]
        pct = row["Доля, %"]
        if not sector: continue
            
        sector_budget = stocks_value * (pct / 100)
        st.markdown(f"**{sector}** (Бюджет: {sector_budget:.0f} ₽)")
        
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
            
        sector_budget = stocks_value * (pct / 100)
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
                
            share_in_portfolio = (planned_amount / total_portfolio_value) * 100 if total_portfolio_value > 0 else 0
            
            table_rows.append({
                "Сектор": sector,
                "Тикер": t,
                "Название": name_map.get(t, t),
                "Балл": score,
                "Планируемая сумма, ₽": planned_amount,
                "Доля в секторе, %": share_in_sector,
                "Доля в портфеле, %": share_in_portfolio,
            })

    planned_amounts = {}
    for r in table_rows:
        planned_amounts[r["Тикер"]] = r["Планируемая сумма, ₽"]
    state.set_global("rebalance_planned_amounts", planned_amounts)

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
            "Планируемая сумма, ₽": "{:.0f}",
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
    st.markdown(f"**Итого распределено:** {total_planned:.0f} ₽ из {stocks_value:.0f} ₽ (Стоимость акций)")
