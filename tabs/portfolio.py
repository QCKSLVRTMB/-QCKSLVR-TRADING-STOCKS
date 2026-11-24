from __future__ import annotations

import streamlit as st
import pandas as pd
import math
from core import state
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close, fetch_many_dividends
from core.ranking import calc_ranking
from core.calc import get_instrument


def _normalize_index_div_yield(raw: float) -> float:
    raw = float(raw)
    if 0 < raw < 1.5:
        return raw * 100
    return raw


def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")
    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("Портфель пуст. Загрузите Excel-файл в боковом меню.")
        return

    df_port = pd.DataFrame(port_data)
    df_stocks_filtered = df_stocks[df_stocks["PRICE"] > 0].copy()
    extreme_date = state.g("extreme_date")
    cb_rate = float(state.g("cb_rate", 14.0))
    tax_rate = float(state.g("tax_rate", 13.0)) / 100.0
    index_div_yield = _normalize_index_div_yield(state.g("index_div_yield", 0.0))

    with st.spinner("Расчёт рейтинга акций портфеля..."):
        df_indices = fetch_moex_indices()
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices["SECID"] == "IMOEX"]
        imoex_curr = imoex_row["CURRENTVALUE"].values[0] if not imoex_row.empty else 0.0
        w_forms = state.g("w_formations")
        df_ranked = calc_ranking(
            df_stocks_filtered, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr,
            portfolio_data=port_data,
        )
        score_map = dict(zip(df_ranked["SECID"], df_ranked["total_score"]))

    # Стоимость по ТВХ (для синхронизации % кеша) и по рынку (для отображения)
    stocks_value_tvh = 0.0
    for p in port_data:
        inst = get_instrument(p["Тикер"], df_stocks)
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        stocks_value_tvh += float(p["ТВХ"]) * float(p["Лотов"]) * lot_size

    def _sync_cash_pct():
        pct = st.session_state["ui_cash_pct"]
        total = stocks_value_tvh / (1 - pct / 100) if pct < 100 else stocks_value_tvh
        cash = total - stocks_value_tvh
        st.session_state["ui_cash_rub"] = float(cash)
        state.set_global("portfolio_cash_pct", pct)
        state.set_global("portfolio_cash", cash)
        state.autosave()

    def _sync_cash_rub():
        cash = st.session_state["ui_cash_rub"]
        total = stocks_value_tvh + cash
        pct = (cash / total * 100) if total != 0 else 0
        st.session_state["ui_cash_pct"] = float(pct)
        state.set_global("portfolio_cash_pct", pct)
        state.set_global("portfolio_cash", cash)
        state.autosave()

    if "ui_cash_pct" not in st.session_state:
        file_cash = state.g("portfolio_cash_file", 0.0)
        total = stocks_value_tvh + file_cash
        pct = (file_cash / total * 100) if total != 0 else 20.0
        st.session_state["ui_cash_pct"] = float(pct)
        st.session_state["ui_cash_rub"] = float(file_cash)

    st.markdown("#### Баланс счета")
    mobile = state.g("mobile_view")
    if mobile:
        st.number_input("Кеш / Долг (Рубли)", value=float(state.g("portfolio_cash", 0.0)), step=1000.0, format="%.2f", key="ui_cash_rub", on_change=_sync_cash_rub)
        st.number_input("Кеш (%)", value=float(state.g("portfolio_cash_pct", 20.0)), step=1.0, format="%.1f", key="ui_cash_pct", on_change=_sync_cash_pct)
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.number_input("Кеш / Долг (Рубли)", value=float(state.g("portfolio_cash", 0.0)), step=1000.0, format="%.2f", key="ui_cash_rub", on_change=_sync_cash_rub)
        with c2:
            st.number_input("Кеш (%)", value=float(state.g("portfolio_cash_pct", 20.0)), step=1.0, format="%.1f", key="ui_cash_pct", on_change=_sync_cash_pct)

    tickers = df_port["Тикер"].tolist()
    with st.spinner("Загрузка дивидендов..."):
        divs_data = fetch_many_dividends(tickers)

    future_divs = state.g("future_dividends", {})
    if not isinstance(future_divs, dict):
        future_divs = {}
    planned_amounts = state.g("rebalance_planned_amounts", {})
    overrides = state.g("ticker_overrides", {})

    if not planned_amounts:
        st.warning("Таблица «Ребалансировка» пуста. Рекомендации будут равны 0.")

    st.caption(f"Ставка ЦБ: **{cb_rate:.2f}%** | Доходность индекса стаб.див: **{index_div_yield:.2f}%** | Налог: **{tax_rate*100:.0f}%**")

    rows = []
    total_value = 0.0
    total_cost = 0.0
    total_gross_div = 0.0
    total_net_div = 0.0

    for _, r in df_port.iterrows():
        t = str(r["Тикер"]).strip()
        avg_price = float(r["ТВХ"])
        lots = int(float(r["Лотов"]))
        inst = get_instrument(t, df_stocks)
        current_price = inst.price if inst.price > 0 else avg_price
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        shares = lots * lot_size

        cost = avg_price * shares
        value = current_price * shares
        pl_rub = value - cost
        pl_pct = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0.0

        if t in overrides and overrides[t].get("div_12m"):
            div_12m = overrides[t]["div_12m"]
        else:
            div_12m_dsi = state.g("div_12m_from_dsi", {})
            if isinstance(div_12m_dsi, dict) and t in div_12m_dsi:
                div_12m = div_12m_dsi[t]
            else:
                div_12m = divs_data.get(t, {}).get("div_12m", 0.0)

        div_yield_tvh = (div_12m / avg_price * 100) if avg_price > 0 else 0.0

        fut_div_per_share = future_divs.get(t, 0.0)
        gross_div = fut_div_per_share * shares
        net_div = gross_div * (1 - tax_rate)

        if div_yield_tvh >= cb_rate and pl_pct > 0:
            asset_color = "green"
        elif div_yield_tvh >= cb_rate and pl_pct <= 0:
            asset_color = "yellow"
        elif div_yield_tvh == 0 and pl_pct > 0:
            asset_color = "orange"
        else:
            asset_color = "red"

        ticker_score = score_map.get(t, 0)
        target_amount = planned_amounts.get(t, 0.0)

        price_for_calc = current_price if current_price > 0 else avg_price
        if price_for_calc > 0 and target_amount > 0:
            target_lots = int(math.floor((target_amount / (price_for_calc * lot_size)) + 0.5))
        else:
            target_lots = 0

        action_lots = target_lots - lots

        if target_amount > 0:
            if action_lots > 0:
                action_str = f"Купить {action_lots}"
            elif action_lots < 0:
                action_str = f"Продать {abs(action_lots)}"
            else:
                action_str = "Держать"
        else:
            action_str = "—"

        total_value += value
        total_cost += cost
        total_gross_div += gross_div
        total_net_div += net_div

        rows.append({
            "Название": inst.name,
            "Тикер": t,
            "Вид актива": asset_color,
            "Баллы": ticker_score,
            "Рыночная цена": current_price,
            "ТВХ": avg_price,
            "Лотов": lots,
            "Вложено, ₽": cost,
            "Текущая стоимость, ₽": value,
            "Прибыль или убыток": pl_rub,
            "P/L %": pl_pct,
            "Дивиденды за 12 мес.": div_12m,
            "Див. доходность": div_yield_tvh,
            "Див брутто": gross_div,
            "Див нетто": net_div,
            "Целевые лоты": target_lots,
            "Действия": action_str,
        })

    df_res = pd.DataFrame(rows)

    # Итоговые метрики с учётом плеча
    cash = float(state.g("portfolio_cash", 0.0))
    equity = total_value + cash
    margin_loan = max(-cash, 0.0)
    div_yield_portfolio = (total_net_div / total_value * 100) if total_value > 0 else 0.0

    st.markdown("#### Итоги портфеля")
    i1, i2, i3, i4, i5 = st.columns(5)
    i1.metric("Собственный капитал", f"{equity:,.0f} ₽")
    i2.metric("Долг (плечо)" if margin_loan > 0 else "Кеш", f"{margin_loan:,.0f} ₽" if margin_loan > 0 else f"{cash:,.0f} ₽")
    i3.metric("Див. брутто (12м)", f"{total_gross_div:,.0f} ₽")
    i4.metric("Див. нетто (12м)", f"{total_net_div:,.0f} ₽")
    i5.metric("Див. доходность", f"{div_yield_portfolio:.2f}%")

    if margin_loan > 0:
        st.warning(
            f"Портфель использует плечо: долг {margin_loan:,.0f} ₽. "
            f"Стоимость активов {total_value:,.0f} ₽, собственный капитал {equity:,.0f} ₽. "
            f"В сценарии «Тактическая докупка» свободных средств нет — сначала погасите долг."
        )

    st.markdown("#### Позиции")

    def style_pl(row):
        styles = [""] * len(row)
        color = row["Вид актива"]
        if color == "green":
            styles[2] = "background-color: #4CAF50; color: #4CAF50;"
        elif color == "yellow":
            styles[2] = "background-color: #FFEB3B; color: #FFEB3B;"
        elif color == "orange":
            styles[2] = "background-color: #FF9800; color: #FF9800;"
        elif color == "red":
            styles[2] = "background-color: #F44336; color: #F44336;"

        score = float(row["Баллы"])
        if score >= 700:
            styles[3] = "background-color: #4CAF50; color: white; font-weight: bold;"
        elif score >= 500:
            styles[3] = "background-color: #FFEB3B; color: black; font-weight: bold;"
        else:
            styles[3] = "background-color: #F44336; color: white; font-weight: bold;"

        if row["Прибыль или убыток"] > 0:
            styles[9] = "color: #4CAF50; font-weight: bold;"
            styles[10] = "color: #4CAF50; font-weight: bold;"
        elif row["Прибыль или убыток"] < 0:
            styles[9] = "color: #F44336; font-weight: bold;"
            styles[10] = "color: #F44336; font-weight: bold;"

        div_yield = row["Див. доходность"]
        if div_yield >= cb_rate:
            styles[12] = "background-color: #4CAF50; color: white; font-weight: bold;"
        elif index_div_yield > 0 and div_yield >= index_div_yield:
            styles[12] = "background-color: #2196F3; color: white; font-weight: bold;"
        else:
            styles[12] = "background-color: #F44336; color: white; font-weight: bold;"

        act = row["Действия"]
        if "Купить" in act:
            styles[16] = "background-color: #C8E6C9; color: #1B5E20; font-weight: bold;"
        elif "Продать" in act:
            styles[16] = "background-color: #FFCDD2; color: #B71C1C; font-weight: bold;"
        return styles

    display_df = df_res[[
        "Название", "Тикер", "Вид актива", "Баллы", "Рыночная цена", "ТВХ", "Лотов",
        "Вложено, ₽", "Текущая стоимость, ₽", "Прибыль или убыток", "P/L %",
        "Дивиденды за 12 мес.", "Див. доходность", "Див брутто", "Див нетто",
        "Целевые лоты", "Действия",
    ]].copy()

    styled_df = (
        display_df.style
        .apply(style_pl, axis=1)
        .format({
            "Вид актива": lambda x: "",
            "Баллы": "{:.0f}",
            "Рыночная цена": "{:.2f}",
            "ТВХ": "{:.2f}",
            "Лотов": "{:.0f}",
            "Вложено, ₽": "{:,.0f}",
            "Текущая стоимость, ₽": "{:,.0f}",
            "Прибыль или убыток": "{:+,.0f}",
            "P/L %": "{:+.2f}%",
            "Дивиденды за 12 мес.": "{:.2f}",
            "Див. доходность": "{:.2f}%",
            "Див брутто": "{:,.0f}",
            "Див нетто": "{:,.0f}",
            "Целевые лоты": "{:.0f}",
        })
    )

    st.dataframe(styled_df, use_container_width=True, hide_index=True, height=40 + 35 * len(df_res) + 6)
    st.caption(
        f"Всего позиций: {len(df_res)} | "
        f"Вложено: {total_cost:,.0f} ₽ | "
        f"Стоимость активов: {total_value:,.0f} ₽ | "
        f"Общий P/L: {total_value - total_cost:+,.0f} ₽ | "
        f"Див. брутто: {total_gross_div:,.0f} ₽ | "
        f"Див. нетто: {total_net_div:,.0f} ₽"
    )
