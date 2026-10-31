import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks, fetch_many_dividends
from core.calc import get_instrument


def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")

    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("📁 **Портфель**\n\nЗагрузите Excel-файл портфеля в боковом меню.")
        return

    df_port = pd.DataFrame(port_data)
    
    # --- Поле Кеш ---
    def _sync_cash():
        state.set_global("portfolio_cash", st.session_state["ui_cash"])
        state.autosave()

    c1, c2 = st.columns([1, 2])
    with c1:
        if "ui_cash" not in st.session_state:
            st.session_state["ui_cash"] = float(state.g("portfolio_cash", 0.0))
            
        st.number_input(
            "Кеш на счету (Рубли)", 
            value=float(state.g("portfolio_cash", 0.0)), 
            step=1000.0, 
            format="%.2f",
            key="ui_cash",
            on_change=_sync_cash
        )
    with c2:
        file_cash = state.g("portfolio_cash_file", 0.0)
        st.write("") # отступ
        st.write("") # отступ
        if file_cash > 0:
            st.caption(f"Справочно из файла: **{file_cash:,.2f} ₽**")

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

    st.markdown("#### Позиции")
    
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
        f"Стоимость акций: **{total_value:,.0f} ₽** · "
        f"Вложено: **{total_cost:,.0f} ₽** · "
        f"Общий P/L: **{total_value - total_cost:+,.0f} ₽**"
    )
