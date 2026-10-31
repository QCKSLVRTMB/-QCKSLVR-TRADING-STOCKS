import streamlit as st
import pandas as pd
import math
from core import state
from core.market import fetch_moex_stocks, fetch_many_dividends
from core.calc import get_instrument


def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")

    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("Портфель пуст. Загрузите Excel-файл в боковом меню.")
        return

    df_port = pd.DataFrame(port_data)
    
    stocks_value = 0.0
    for p in port_data:
        inst = get_instrument(p["Тикер"], df_stocks)
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        stocks_value += p["ТВХ"] * p["Лотов"] * lot_size

    def _sync_cash_pct():
        pct = st.session_state["ui_cash_pct"]
        total = stocks_value / (1 - pct/100) if pct < 100 else stocks_value
        cash = total - stocks_value
        st.session_state["ui_cash_rub"] = float(max(0, cash))
        state.set_global("portfolio_cash_pct", pct)
        state.set_global("portfolio_cash", cash)
        state.autosave()

    def _sync_cash_rub():
        cash = st.session_state["ui_cash_rub"]
        total = stocks_value + cash
        pct = (cash / total * 100) if total > 0 else 0
        st.session_state["ui_cash_pct"] = float(pct)
        state.set_global("portfolio_cash_pct", pct)
        state.set_global("portfolio_cash", cash)
        state.autosave()

    if "ui_cash_pct" not in st.session_state:
        file_cash = state.g("portfolio_cash_file", 0.0)
        total = stocks_value + file_cash
        pct = (file_cash / total * 100) if total > 0 else 20.0
        st.session_state["ui_cash_pct"] = float(pct)
        st.session_state["ui_cash_rub"] = float(file_cash)
        
    st.markdown("#### Баланс счета")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "Кеш (Рубли)", 
            value=float(state.g("portfolio_cash", 0.0)), 
            step=1000.0, format="%.2f", key="ui_cash_rub", on_change=_sync_cash_rub
        )
    with c2:
        st.number_input(
            "Кеш (%)", 
            value=float(state.g("portfolio_cash_pct", 20.0)), 
            step=1.0, format="%.1f", key="ui_cash_pct", on_change=_sync_cash_pct
        )

    tickers = df_port["Тикер"].tolist()
    with st.spinner("Загрузка дивидендов..."):
        divs_data = fetch_many_dividends(tickers)

    cb_rate = state.g("cb_rate", 14.0)
    future_divs = state.g("future_dividends", {})
    planned_amounts = state.g("rebalance_planned_amounts", {})
    
    if not planned_amounts:
        st.warning("Внимание: Таблица «Ребалансировка» пуста. Доступные лоты и рекомендации по действиям будут равны 0.")

    rows = []
    total_value = 0.0
    total_cost = 0.0

    for _, r in df_port.iterrows():
        t = r["Тикер"]
        avg_price = float(r["ТВХ"])
        lots = int(r["Лотов"])
        
        inst = get_instrument(t, df_stocks)
        current_price = inst.price if inst.price > 0 else avg_price
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        shares = lots * lot_size
        
        cost = avg_price * shares
        value = current_price * shares
        pl_rub = value - cost
        pl_pct = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0.0
        
        # 1. Дивиденды за 12 месяцев строго с dohod.ru
        div_12m = divs_data.get(t, {}).get("div_12m", 0.0)
        div_yield_tvh = (div_12m / avg_price * 100) if avg_price > 0 else 0.0
        
        # 2. Брутто и Нетто строго из вкладки "Дивиденды" в Excel
        fut_div_per_share = future_divs.get(t, 0.0)
        gross_div = fut_div_per_share * shares
        net_div = gross_div * (1 - 0.13)
        
        # 3. Расчет лотов (все целые числа)
        target_amount = planned_amounts.get(t, 0.0)
        tvh_safe = avg_price if avg_price > 0 else current_price
        
        if tvh_safe > 0 and target_amount > 0:
            target_lots = math.floor((target_amount / (tvh_safe * lot_size)) + 0.5)
        else:
            target_lots = 0
            
        if div_yield_tvh > 0 and cb_rate > 0 and target_lots > 0:
            lots_by_yield = math.floor((target_lots * (div_yield_tvh / cb_rate)) + 0.5)
            action_lots = lots_by_yield - lots
            if action_lots > 0:
                action_str = f"Купить {action_lots}"
            elif action_lots < 0:
                action_str = f"Продать {abs(action_lots)}"
            else:
                action_str = "Держать"
        else:
            lots_by_yield = 0
            action_str = "—"
            
        total_value += value
        total_cost += cost
        
        rows.append({
            "Название": inst.name,
            "Тикер": t,
            "Рыночная цена": current_price,
            "ТВХ": avg_price,
            "Лотов": lots,
            "Прибыль или убыток": pl_rub,
            "P/L %": pl_pct,
            "Дивиденды за 12 мес.": div_12m,
            "Див брутто": gross_div,
            "Див нетто": net_div,
            "Доступно лотов": target_lots,
            "Лотов по доходности": lots_by_yield,
            "Действия": action_str,
        })

    df_res = pd.DataFrame(rows)

    st.markdown("#### Позиции")
    
    def style_pl(row):
        styles = [""] * len(row)
        
        # Индексы колонок: Прибыль (5), P/L % (6), Действия (12)
        if row["Прибыль или убыток"] > 0:
            styles[5] = "color: #4CAF50; font-weight: bold;"
            styles[6] = "color: #4CAF50; font-weight: bold;"
        elif row["Прибыль или убыток"] < 0:
            styles[5] = "color: #F44336; font-weight: bold;"
            styles[6] = "color: #F44336; font-weight: bold;"
            
        act = row["Действия"]
        if "Купить" in act:
            styles[12] = "background-color: #C8E6C9; color: #1B5E20; font-weight: bold;"
        elif "Продать" in act:
            styles[12] = "background-color: #FFCDD2; color: #B71C1C; font-weight: bold;"
            
        return styles

    display_df = df_res[[
        "Название", "Тикер", "Рыночная цена", "ТВХ", "Лотов",
        "Прибыль или убыток", "P/L %", 
        "Дивиденды за 12 мес.", "Див брутто", "Див нетто", 
        "Доступно лотов", "Лотов по доходности", "Действия"
    ]].copy()

    styled_df = (
        display_df.style
        .apply(style_pl, axis=1)
        .format({
            "Рыночная цена": "{:.2f}",
            "ТВХ": "{:.2f}",
            "Лотов": "{:.0f}",
            "Прибыль или убыток": "{:+.0f}",
            "P/L %": "{:+.2f}%",
            "Дивиденды за 12 мес.": "{:.2f}",
            "Див брутто": "{:.0f}",
            "Див нетто": "{:.0f}",
            "Доступно лотов": "{:.0f}",
            "Лотов по доходности": "{:.0f}",
        })
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=40 + 35 * len(df_res) + 6
    )

    st.caption(
        f"Всего позиций: {len(df_res)} · "
        f"Стоимость акций: {total_value:.0f} ₽ · "
        f"Вложено: {total_cost:.0f} ₽ · "
        f"Общий P/L: {total_value - total_cost:+.0f} ₽"
    )
