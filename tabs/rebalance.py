from __future__ import annotations
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
    cash_pct = state.g("portfolio_cash_pct", 0.0)
    target_cash_pct = float(state.g("cash_reserve", 20.0))
    
    current_stocks_value = 0.0
    for p in positions:
        inst = get_instrument(p["Тикер"], df_stocks)
        price = inst.price if inst.price > 0 else p["ТВХ"]
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        current_stocks_value += price * p["Лотов"] * lot_size
    
    total_portfolio_value = current_stocks_value + cash
    
    st.markdown("### 1. Настройка секторов")
    
    scenario = st.radio(
        "Сценарий распределения:",
        [
            "Без продажи (Перераспределить весь портфель + кеш)",
            "С продажей (Жесткое приведение к целевой структуре)",
            "Тактическая докупка (Распределить ТОЛЬКО текущий свободный кеш)"
        ],
        horizontal=False,
        help=(
            "1. Весь портфель пересчитывается, кеш докупает акции до целевых долей.\n"
            "2. Система может предложить продажу, чтобы достичь целевого % кеша.\n"
            "3. Идеально для усреднения: распределяется только доступный кеш."
        )
    )
    
    if "Без продажи" in scenario:
        base_budget = current_stocks_value + cash
        scenario_desc = "Весь портфель перераспределяется за счет докупки"
    elif "С продажей" in scenario:
        base_budget = total_portfolio_value * (1 - target_cash_pct / 100)
        scenario_desc = f"Приведение к структуре с {target_cash_pct:.1f}% кеша"
    else:
        base_budget = cash
        scenario_desc = "Распределяем только доступные деньги, не трогая текущие позиции"
    
    st.info(
        f"Текущие акции: {current_stocks_value:,.0f} ₽ | "
        f"Кеш: {cash:,.0f} ₽ ({cash_pct:.1f}%) | "
        f"Всего портфель: {total_portfolio_value:,.0f} ₽\n\n"
        f"**Режим:** {scenario_desc}\n"
        f"**База для распределения:** {base_budget:,.0f} ₽"
    )
    
    if "rebal_sectors" not in st.session_state:
        saved = state.g("rebal_sectors_data", None)
        if saved:
            st.session_state["rebal_sectors"] = pd.DataFrame(saved)
        else:
            st.session_state["rebal_sectors"] = pd.DataFrame([
                {"Сектор": s, "Доля, %": 0.0} for s in DEFAULT_SECTORS
            ])
    
    edited_sectors = st.data_editor(
        st.session_state["rebal_sectors"],
        num_rows="dynamic",
        use_container_width=True,
        key="rebal_sectors_editor_v3",
        column_config={
            "Сектор": st.column_config.TextColumn("Название сектора", required=True),
            "Доля, %": st.column_config.NumberColumn("Целевая доля, %", min_value=0.0, max_value=100.0, step=1.0, format="%.1f%%")
        }
    )
    
    st.session_state["rebal_sectors"] = edited_sectors
    state.set_global("rebal_sectors_data", edited_sectors.to_dict('records'))
    
    total_pct = edited_sectors["Доля, %"].sum()
    if total_pct > 100.0:
        st.markdown(
            f"<div style='background-color: #ffcccc; padding: 10px; border-radius: 5px; color: red; font-weight: bold;'>"
            f"Ошибка: Сумма долей секторов равна {total_pct:.1f}%. Сумма не должна превышать 100%.</div>", 
            unsafe_allow_html=True
        )
    
    st.markdown("### 2. Выбор активов (тикеров)")
    st.caption("Тикеры подтягиваются автоматически на основе секторов из загруженного портфеля.")
    
    all_tickers = sorted(df_stocks["SECID"].unique().tolist())
    
    if "rebal_tickers" not in st.session_state:
        saved = state.g("rebal_tickers_data", None)
        if saved:
            st.session_state["rebal_tickers"] = saved
        else:
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
        if not sector:
            continue
        
        sector_budget = base_budget * (pct / 100)
        st.markdown(f"**{sector}** (Бюджет: {sector_budget:,.0f} ₽)")
        
        default_tickers = st.session_state["rebal_tickers"].get(sector, [])
        
        if f"tags_{sector}" not in st.session_state:
            st.session_state[f"tags_{sector}"] = default_tickers
        
        selected = st.multiselect(
            f"Активы в секторе «{sector}»",
            options=all_tickers,
            key=f"tags_{sector}",
            label_visibility="collapsed"
        )
        
        st.session_state["rebal_tickers"][sector] = selected
    
    state.set_global("rebal_tickers_data", st.session_state["rebal_tickers"])
    
    st.markdown("### 3. Итоговая таблица действий")
    table_rows = []
    
    for _, row in edited_sectors.iterrows():
        sector = row["Сектор"]
        pct = row["Доля, %"]
        if not sector:
            continue
        
        tickers = st.session_state["rebal_tickers"].get(sector, [])
        if not tickers:
            continue
        
        sector_budget = base_budget * (pct / 100)
        sector_scores = {t: score_map.get(t, 0) for t in tickers}
        total_sector_score = sum(sector_scores.values())
        
        for t in tickers:
            score = sector_scores[t]
            if total_sector_score > 0:
                planned_amount = sector_budget * (score / total_sector_score)
                share_in_sector = (score / total_sector_score) * 100
            else:
                planned_amount = sector_budget / len(tickers) if len(tickers) > 0 else 0.0
                share_in_sector = 100 / len(tickers) if len(tickers) > 0 else 0.0
            
            # === НОВОЕ: Доля в портфеле от общей стоимости портфеля ===
            share_in_portfolio = (planned_amount / total_portfolio_value) * 100 if total_portfolio_value > 0 else 0
            
            # Находим текущие лоты
            current_lots = 0
            current_tvh = 0.0
            for p in positions:
                if p["Тикер"] == t:
                    current_lots = p["Лотов"]
                    current_tvh = p["ТВХ"]
                    break
            
            inst = get_instrument(t, df_stocks)
            price = inst.price if inst.price > 0 else current_tvh
            lot_size = inst.lot_size if inst.lot_size > 0 else 1
            
            if price > 0 and planned_amount > 0:
                target_lots = int(planned_amount // (price * lot_size))
            else:
                target_lots = 0
            
            action_lots = target_lots - current_lots
            
            if action_lots > 0:
                action_str = f"Купить {action_lots}"
            elif action_lots < 0 and "С продажей" in scenario:
                action_str = f"Продать {abs(action_lots)}"
            else:
                action_str = "Держать"
            
            table_rows.append({
                "Сектор": sector,
                "Тикер": t,
                "Название": name_map.get(t, t),
                "Балл": score,
                "Планируемая сумма, ₽": planned_amount,
                "Доля в секторе, %": share_in_sector,
                "Доля в портфеле, %": share_in_portfolio,  # <-- ДОБАВЛЕНО
                "Текущие лоты": current_lots,
                "Целевые лоты": target_lots,
                "Действие": action_str,
            })
    
    if table_rows:
        planned_amounts = {}
        for r in table_rows:
            planned_amounts[r["Тикер"]] = r["Планируемая сумма, ₽"]
        state.set_global("rebalance_planned_amounts", planned_amounts)
    
    if not table_rows:
        st.info("Добавьте тикеры в секторы, чтобы увидеть расчет.")
        return
    
    df_result = pd.DataFrame(table_rows)
    
    # === НОВОЕ: Сортировка по "Доля в портфеле, %" по убыванию ===
    df_result = df_result.sort_values("Доля в портфеле, %", ascending=False).reset_index(drop=True)
    
    def style_row(row):
        styles = [""] * len(row)
        if row["Балл"] == 0:
            styles[3] = "background-color: #F44336; color: white;"
        else:
            styles[3] = "background-color: #4CAF50; color: white;"
        
        act = row["Действие"]
        if "Купить" in act:
            styles[9] = "background-color: #C8E6C9; color: #1B5E20; font-weight: bold;"
        elif "Продать" in act:
            styles[9] = "background-color: #FFCDD2; color: #B71C1C; font-weight: bold;"
            
        return styles
    
    styled_df = (
        df_result.style
        .apply(style_row, axis=1)
        .format({
            "Балл": "{:.0f}",
            "Планируемая сумма, ₽": "{:.0f}",
            "Доля в секторе, %": "{:.1f}%",
            "Доля в портфеле, %": "{:.2f}%",  # <-- ДОБАВЛЕНО
            "Текущие лоты": "{:.0f}",
            "Целевые лоты": "{:.0f}",
        })
    )
    
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=40 + 35 * len(df_result) + 6
    )
    
    total_planned = df_result["Планируемая сумма, ₽"].sum()
    st.markdown(f"**Итого распределено:** {total_planned:,.0f} ₽ из {base_budget:,.0f} ₽")
    
    if "Тактическая" in scenario:
        future_cash_needed = (total_portfolio_value * (target_cash_pct / 100)) - cash
        if future_cash_needed > 0:
            st.info(
                f"💡 **Напоминание:** После этой докупки доля кеша временно снизится. "
                f"Чтобы в будущем вернуться к целевому уровню {target_cash_pct:.1f}%, "
                f"вам потребуется пополнить счет на **{future_cash_needed:,.0f} ₽** "
                f"(или высвободить эту сумму при росте активов)."
            )
