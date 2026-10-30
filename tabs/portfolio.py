import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks, fetch_many_dividends
from core.calc import get_instrument


def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")

    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info(
            "📁 **Портфель**\n\n"
            "Загрузите Excel-файл портфеля в боковом меню.\n\n"
            "В файле достаточно трёх колонок:\n"
            "- **Тикер** (например LKOH)\n"
            "- **ТВХ** (или «Средняя цена»)\n"
            "- **Количество лотов** (или «Лотов»)"
        )
        return

    df_port = pd.DataFrame(port_data)
    
    # Загружаем дивиденды для всех тикеров портфеля
    tickers = df_port["Тикер"].tolist()
    with st.spinner("Загрузка дивидендов..."):
        divs_data = fetch_many_dividends(tickers)

    cb_rate = state.g("cb_rate", 14.0)
    
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
        
        cost = avg_price * lots * lot_size
        value = current_price * lots * lot_size
        pl_rub = value - cost
        pl_pct = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0.0
        
        div_12m = divs_data.get(t, {}).get("div_12m", 0.0)
        div_yield_tvh = (div_12m / avg_price * 100) if avg_price > 0 else 0.0
        rec_max_price = (div_12m / (cb_rate / 100)) if div_12m > 0 and cb_rate > 0 else 0.0
        
        total_value += value
        total_cost += cost
        
        rows.append({
            "Тикер": t,
            "Название": inst.name,
            "Лотов": lots,
            "ТВХ": avg_price,
            "Цена": current_price,
            "Стоимость": value,
            "P/L ₽": pl_rub,
            "P/L %": pl_pct,
            "Див 12м": div_12m,
            "Див.дох. к ТВХ %": div_yield_tvh,
            "Рек. макс. цена": rec_max_price,
            "_lot_size": lot_size
        })

    df_res = pd.DataFrame(rows)

    # ---------------- Таблица ----------------
    st.markdown("#### Позиции")
    
    # Форматирование
    def style_pl(row):
        styles = [""] * len(row)
        if row["P/L ₽"] > 0:
            styles[6] = "color: #4CAF50; font-weight: bold;"
            styles[7] = "color: #4CAF50; font-weight: bold;"
        elif row["P/L ₽"] < 0:
            styles[6] = "color: #F44336; font-weight: bold;"
            styles[7] = "color: #F44336; font-weight: bold;"
        return styles

    display_df = df_res[[
        "Тикер", "Название", "Лотов", "ТВХ", "Цена", 
        "Стоимость", "P/L ₽", "P/L %", 
        "Див 12м", "Див.дох. к ТВХ %", "Рек. макс. цена"
    ]].copy()

    styled_df = (
        display_df.style
        .apply(style_pl, axis=1)
        .format({
            "ТВХ": "{:.2f}",
            "Цена": "{:.2f}",
            "Стоимость": "{:,.0f}",
            "P/L ₽": "{:+,.0f}",
            "P/L %": "{:+.2f}%",
            "Див 12м": "{:.2f}",
            "Див.дох. к ТВХ %": "{:.2f}%",
            "Рек. макс. цена": "{:.2f}",
        })
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=40 + 35 * len(df_res) + 6
    )

    st.caption(
        f"Всего позиций: **{len(df_res)}** · "
        f"Стоимость: **{total_value:,.0f} ₽** · "
        f"Вложено: **{total_cost:,.0f} ₽** · "
        f"Общий P/L: **{total_value - total_cost:+,.0f} ₽**"
    )

    # ---------------- Калькулятор усреднения ----------------
    st.markdown("---")
    st.markdown("### 🧮 Калькулятор усреднения позиции")

    tickers = df_res["Тикер"].tolist()
    
    sel_ticker = st.selectbox(
        "Актив из портфеля",
        tickers,
        key="avg_ticker",
        help="Выберите позицию — ТВХ и количество лотов подставятся автоматически.",
    )

    row = df_res[df_res["Тикер"] == sel_ticker].iloc[0]
    old_avg = row["ТВХ"]
    old_lots = row["Лотов"]
    current_price = row["Цена"]
    lot_size = row["_lot_size"]
    decimals = 2 if current_price > 1 else 4
    div_12m = row["Див 12м"]
    
    # DSI из Excel
    fund = state.g("fundamental_data", {}) or {}
    dsi_raw = fund.get(sel_ticker, {}).get("dsi")
    dsi_score = None
    if dsi_raw is not None:
        try:
            v = float(dsi_raw)
            dsi_score = v * 100 if v <= 1.5 else v
        except (TypeError, ValueError):
            dsi_score = None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Текущее ТВХ", f"{old_avg:.{decimals}f} ₽")
    c2.metric("Лотов в портфеле", str(old_lots))
    c3.metric("Текущая цена", f"{current_price:.{decimals}f} ₽")
    c4.metric("Див. на акцию (12м)", f"{div_12m:.2f} ₽" if div_12m else "—")

    st.markdown("#### Докупка")
    ic1, ic2 = st.columns(2)
    with ic1:
        new_price = st.number_input(
            "Цена покупки, ₽", min_value=0.0, value=float(current_price), step=0.01,
            format=f"%.{decimals}f", key=f"avg_new_price_{sel_ticker}"
        )
    with ic2:
        new_lots = st.number_input(
            "Лотов докупить", min_value=0, value=0, step=1, key=f"avg_new_lots_{sel_ticker}"
        )

    if new_lots > 0 and new_price > 0:
        old_cost = old_avg * old_lots
        new_cost = new_price * new_lots
        total_lots = old_lots + new_lots
        new_avg = (old_cost + new_cost) / total_lots if total_lots > 0 else 0.0

        st.markdown("#### Результат усреднения")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Новое ТВХ", f"{new_avg:.{decimals}f} ₽", f"{new_avg - old_avg:+.{decimals}f} ₽" if old_avg else None)
        r2.metric("Всего лотов", str(total_lots), f"+{new_lots}")
        r3.metric("Стоимость новой позиции", f"{new_avg * total_lots * lot_size:,.0f} ₽")
        r4.metric("Затраты на докупку", f"{new_price * new_lots * lot_size:,.0f} ₽")

        st.markdown("#### Метрики позиции")
        m1, m2, m3, m4 = st.columns(4)

        if current_price > 0 and new_avg > 0:
            pl_rub = (current_price - new_avg) * total_lots * lot_size
            pl_pct = (current_price / new_avg - 1) * 100
            m1.metric("P/L по новой позиции", f"{pl_rub:+,.0f} ₽", f"{pl_pct:+.2f}%")
        else:
            m1.metric("P/L по новой позиции", "—")

        if div_12m > 0 and new_avg > 0:
            yield_old = (div_12m / old_avg * 100) if old_avg > 0 else 0.0
            yield_new = div_12m / new_avg * 100
            delta = yield_new - yield_old if old_avg > 0 else None
            m2.metric("Див. доходность (новая)", f"{yield_new:.2f}%", f"{delta:+.2f}%" if delta is not None else None)
        else:
            m2.metric("Див. доходность (новая)", "—")

        annual_div = div_12m * total_lots * lot_size
        m3.metric("Годовой дивидендный поток", f"{annual_div:,.0f} ₽" if annual_div > 0 else "—")
        m4.metric("DSI", f"{dsi_score:.0f}" if dsi_score is not None else "—")
