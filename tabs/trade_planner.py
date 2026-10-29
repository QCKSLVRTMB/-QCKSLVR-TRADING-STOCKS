import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_candles
from core.calc import get_instrument
from core import charts
from core.config import INTERVALS

def render_trade_planner(ticker: str, df_stocks: pd.DataFrame):
    inst = get_instrument(ticker, df_stocks)
    tdata = state.ticker(ticker)
    port_data = state.g("portfolio_data", {}).get(ticker, {})

    st.subheader(f"{ticker} — {inst.name} (Лот: {inst.lot_size})")
    
    c1, c2 = st.columns(2)
    with c1:
        buy_level = st.number_input("Уровень покупок (SL)", value=float(tdata.get("buy_level", 0.0)), format="%.2f")
    with c2:
        sell_level = st.number_input("Уровень продаж (TP)", value=float(tdata.get("sell_level", 0.0)), format="%.2f")
    
    tdata["buy_level"] = buy_level
    tdata["sell_level"] = sell_level

    st.markdown("#### Расчет усреднения (ТВХ)")
    if "entries" not in tdata: tdata["entries"] = []
    
    rows = []
    if port_data:
        rows.append({"Цена": port_data["avg_price"], "Лотов": port_data["lots"], "Комментарий": "Из портфеля", "Lock": True})
    for e in tdata["entries"]:
        rows.append({"Цена": e["price"], "Лотов": e["qty"], "Комментарий": e.get("note", ""), "Lock": False})
        
    # Создаем пустой каркас, чтобы st.data_editor не терял колонки
    if not rows:
        df = pd.DataFrame(columns=["Цена", "Лотов", "Комментарий", "Lock"])
    else:
        df = pd.DataFrame(rows)
        
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Цена": st.column_config.NumberColumn(format="%.2f", step=inst.min_step),
            "Лотов": st.column_config.NumberColumn(step=1),
            "Комментарий": st.column_config.TextColumn(),
            "Lock": None # Скрываем
        },
        disabled=["Цена", "Лотов"] if port_data else []
    )
    
    # Безопасное обновление entries (предотвращает KeyError)
    if not edited.empty and "Цена" in edited.columns and "Лотов" in edited.columns:
        tdata["entries"] = [{"price": r["Цена"], "qty": int(r["Лотов"]), "note": r["Комментарий"]} for _, r in edited.iterrows() if not r.get("Lock", False)]

        # Метрики
        total_lots = edited["Лотов"].sum()
        total_cost = (edited["Цена"] * edited["Лотов"] * inst.lot_size).sum()
        
        if total_lots > 0:
            avg_price = total_cost / (total_lots * inst.lot_size)
            st.metric("Средняя цена (ТВХ)", f"{avg_price:.2f} ₽")
            
            if sell_level > 0:
                st.metric("Доходность до продажи", f"{(sell_level / avg_price - 1) * 100:.2f}%")
            if buy_level > 0:
                st.metric("Риск до покупки", f"{(1 - buy_level / avg_price) * 100:.2f}%")

    st.markdown("#### График")
    df_candles = fetch_moex_candles(ticker, interval=24)
    if not df_candles.empty:
        fig = charts.build_figure(df_candles.tail(100), tf_name="D1", title=ticker, decimals=inst.decimals, mobile=state.g("mobile_view"))
        st.plotly_chart(fig, use_container_width=True)
