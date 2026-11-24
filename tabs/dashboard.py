import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from core import state
from core.market import fetch_moex_stocks, fetch_moex_candles, fetch_moex_indices, fetch_extreme_close
from core.config import INDEX_META
from core.calc import get_instrument


def _portfolio_history_curve(positions, df_stocks, days_back=180):
    """Кривая стоимости портфеля во времени (аппроксимация: текущие веса, buy-and-hold)."""
    series = {}
    weights = {}
    for p in positions:
        t = p["Тикер"]
        inst = get_instrument(t, df_stocks)
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        w = int(p["Лотов"]) * lot_size
        if w <= 0:
            continue
        df = fetch_moex_candles(t, interval=24, days_back=days_back)
        if df.empty:
            continue
        series[t] = df["Close"]
        weights[t] = w
    if not series:
        return None
    closes = pd.DataFrame(series).sort_index().ffill().dropna(how="all")
    if closes.empty:
        return None
    w_vec = pd.Series(weights).reindex(closes.columns).fillna(0.0)
    value = (closes * w_vec).sum(axis=1)
    return value


def render_dashboard(df_stocks: pd.DataFrame):
    st.subheader("Дашборд портфеля")

    positions = state.g("portfolio_data", [])
    cash = state.g("portfolio_cash", 0.0)
    tax_rate = float(state.g("tax_rate", 13.0)) / 100.0

    if not positions:
        st.info("Загрузите портфель для отображения дашборда.")
        return

    rows = []
    total_stocks_val = 0.0
    total_cost = 0.0
    total_gross_div = 0.0
    sector_agg = {}

    for p in positions:
        t = p["Тикер"]
        avg_price = float(p["ТВХ"])
        lots = int(p["Лотов"])
        sec = str(p.get("Сектор", "Разное")).strip()

        inst = get_instrument(t, df_stocks)
        current_price = inst.price if inst.price > 0 else avg_price
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        shares = lots * lot_size

        val = current_price * shares
        cost = avg_price * shares
        pl_pct = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0.0

        divs = state.g("div_12m_from_dsi", {})
        div_12m = divs.get(t, 0.0) if isinstance(divs, dict) else 0.0
        if not div_12m:
            div_12m = state.g("future_dividends", {}).get(t, 0.0)
        gross_div = div_12m * shares

        total_stocks_val += val
        total_cost += cost
        total_gross_div += gross_div
        sector_agg[sec] = sector_agg.get(sec, 0.0) + val

        rows.append({
            "Тикер": t,
            "Название": inst.name,
            "Сектор": sec,
            "Стоимость": val,
            "Вложено": cost,
            "P/L %": pl_pct,
        })

    df_port = pd.DataFrame(rows)
    equity = total_stocks_val + cash
    margin_loan = max(-cash, 0.0)
    leverage = (total_stocks_val / equity) if equity > 0 else 0.0
    total_net_div = total_gross_div * (1 - tax_rate)
    div_yield_portfolio = (total_net_div / total_stocks_val * 100) if total_stocks_val > 0 else 0.0

    # ============================================================
    # 0. KPI
    # ============================================================
    st.markdown("### Ключевые показатели")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Собственный капитал", f"{equity:,.0f} ₽")
    k2.metric("Стоимость активов", f"{total_stocks_val:,.0f} ₽")
    k3.metric("Долг (плечо)" if margin_loan > 0 else "Кеш",
              f"{margin_loan:,.0f} ₽" if margin_loan > 0 else f"{cash:,.0f} ₽")
    k4.metric("Оборот плеча", f"{leverage:.2f}x" if margin_loan > 0 else "—")
    k5.metric("Див. нетто (12м)", f"{total_net_div:,.0f} ₽")
    k6.metric("Див. доходность", f"{div_yield_portfolio:.2f}%")

    if margin_loan > 0:
        st.warning(f"Портфель на плече: долг {margin_loan:,.0f} ₽, оборот {leverage:.2f}x.")

    # ============================================================
    # 1. СОСТАВ ПОРТФЕЛЯ
    # ============================================================
    st.markdown("### Состав портфеля по бумагам")
    labels = df_port["Название"].tolist()
    values = df_port["Стоимость"].tolist()
    if cash > 0:
        labels.append("Рубли (Кеш)")
        values.append(cash)

    fig_pie = go.Figure(data=[go.Pie(
        labels=labels, values=values, hole=.5,
        textinfo='label+percent', insidetextorientation='radial'
    )])
    fig_pie.update_layout(showlegend=True, height=500,
                          margin=dict(t=30, b=30, l=30, r=30))
    st.plotly_chart(fig_pie, use_container_width=True)

    # ============================================================
    # 2. РАСПРЕДЕЛЕНИЕ ПО СЕКТОРАМ (текущее vs целевое)
    # ============================================================
    st.markdown("### Распределение по секторам")
    target_sectors = state.g("rebal_sectors_data", [])
    target_map = {}
    if target_sectors:
        for s in target_sectors:
            name = str(s.get("Сектор", "")).strip()
            if name:
                target_map[name] = float(s.get("Доля, %", 0.0))

    sec_df = pd.DataFrame({
        "Сектор": list(sector_agg.keys()),
        "Текущая доля, %": [v / total_stocks_val * 100 if total_stocks_val > 0 else 0 for v in sector_agg.values()],
    })
    sec_df["Целевая доля, %"] = sec_df["Сектор"].map(target_map).fillna(0.0)
    sec_df = sec_df.sort_values("Текущая доля, %", ascending=False)

    fig_sec = go.Figure()
    fig_sec.add_trace(go.Bar(x=sec_df["Сектор"], y=sec_df["Текущая доля, %"],
                             name="Текущая доля", marker_color="#1976D2"))
    if target_map:
        fig_sec.add_trace(go.Scatter(x=sec_df["Сектор"], y=sec_df["Целевая доля, %"],
                                     mode="markers", name="Целевая доля",
                                     marker=dict(color="#F44336", size=10, symbol="diamond")))
    fig_sec.update_layout(height=400, barmode="group", plot_bgcolor="white",
                          yaxis=dict(title="Доля, %", showgrid=True, gridcolor="lightgray"),
                          margin=dict(t=30, b=30, l=30, r=30))
    st.plotly_chart(fig_sec, use_container_width=True)

    # ============================================================
    # 3. БЕНЧМАРКИНГ (реальная кривая портфеля vs IMOEX)
    # ============================================================
    st.markdown("### Бенчмаркинг")
    st.caption("Сравнение динамики портфеля с индексом IMOEX за 6 месяцев. "
               "Портфель рассчитан при текущих весах (buy-and-hold аппроксимация).")

    with st.spinner("Загрузка истории портфеля и IMOEX..."):
        df_imoex = fetch_moex_candles("IMOEX", interval=24, days_back=180, market="index")
        port_curve = _portfolio_history_curve(positions, df_stocks, days_back=180)

    if not df_imoex.empty and port_curve is not None and not port_curve.empty:
        common = df_imoex.index.intersection(port_curve.index)
        if len(common) > 2:
            imoex = df_imoex.loc[common, "Close"]
            port = port_curve.loc[common]
            imoex_ret = (imoex / imoex.iloc[0] - 1) * 100
            port_ret = (port / port.iloc[0] - 1) * 100

            fig_bench = go.Figure()
            fig_bench.add_trace(go.Scatter(x=imoex.index, y=imoex_ret, mode="lines",
                                           name="IMOEX", line=dict(color="#1976D2", width=2)))
            fig_bench.add_trace(go.Scatter(x=port.index, y=port_ret, mode="lines",
                                           name="Портфель", line=dict(color="#26a69a", width=2)))
            fig_bench.update_layout(height=400, plot_bgcolor="white",
                                    yaxis=dict(title="Доходность, %", showgrid=True, gridcolor="lightgray"),
                                    xaxis=dict(showgrid=True, gridcolor="lightgray"),
                                    hovermode="x unified", margin=dict(t=30, b=30, l=30, r=30))
            st.plotly_chart(fig_bench, use_container_width=True)
            st.caption(f"Портфель за период: {port_ret.iloc[-1]:+.2f}% | IMOEX: {imoex_ret.iloc[-1]:+.2f}%")
    else:
        st.warning("Не удалось построить кривую портфеля (нет данных по позициям).")

    # ============================================================
    # 4. ЭФФЕКТИВНОСТЬ ОТРАСЛЕВЫХ ИНДЕКСОВ
    # ============================================================
    st.markdown("### Эффективность отраслевых индексов")
    df_indices = fetch_moex_indices()
    extreme_date = state.g("extreme_date")

    if not df_indices.empty:
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID'] == 'IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0
        if imoex_ext > 0 and imoex_curr > 0:
            imoex_chg = (imoex_curr / imoex_ext - 1) * 100
            idx_rows = []
            for ticker, meta in INDEX_META.items():
                row = df_indices[df_indices['SECID'] == ticker]
                if row.empty:
                    continue
                curr = row['CURRENTVALUE'].values[0]
                if curr == 0:
                    continue
                ext, _ = fetch_extreme_close(ticker, extreme_date)
                if ext > 0:
                    chg = (curr / ext - 1) * 100
                    idx_rows.append({"name": meta["name"], "color": meta["color"], "rel": chg - imoex_chg})
            if idx_rows:
                df_idx = pd.DataFrame(idx_rows).sort_values("rel", ascending=False)
                fig_idx = go.Figure(go.Bar(
                    x=df_idx["name"], y=df_idx["rel"], marker_color=df_idx["color"],
                    text=df_idx["rel"].apply(lambda x: f"{x:.2f}%"), textposition="outside"
                ))
                fig_idx.update_layout(height=400, plot_bgcolor="white",
                                      yaxis=dict(showgrid=True, gridcolor="lightgray", title="Отн. сила, %"),
                                      xaxis=dict(showgrid=False), margin=dict(t=30, b=30, l=30, r=30))
                st.plotly_chart(fig_idx, use_container_width=True)

    # ============================================================
    # 5. ДИВИДЕНДНЫЙ КАЛЕНДАРЬ (по позициям портфеля)
    # ============================================================
    st.markdown("### Дивидендный календарь")
    future_div_list = state.g("future_div_list", [])
    future_divs_dict = state.g("future_dividends", {})
    if not future_div_list and "_list" in future_divs_dict:
        future_div_list = future_divs_dict["_list"]

    port_tickers = {p["Тикер"] for p in positions}
    cal_rows = []
    for d in future_div_list:
        t = d["Тикер"]
        if t not in port_tickers:
            continue
        p = next(x for x in positions if x["Тикер"] == t)
        inst = get_instrument(t, df_stocks)
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        shares = int(p["Лотов"]) * lot_size
        gross = d["Дивиденд"] * shares
        net = gross * (1 - tax_rate)
        dt_close = pd.to_datetime(d.get("Дата закрытия реестра", ""), format="%d.%m.%Y", errors="coerce")
        cal_rows.append({"Тикер": t, "Название": inst.name, "Дивиденд, ₽": d["Дивиденд"],
                         "Брутто": gross, "Нетто": net, "Дата": dt_close})

    if not cal_rows:
        st.info("По позициям портфеля будущих дивидендов не найдено.")
    else:
        df_cal = pd.DataFrame(cal_rows).sort_values("Дата")
        df_cal["Дата"] = df_cal["Дата"].dt.strftime("%d.%m.%Y")
        st.dataframe(df_cal.style.format({"Дивиденд, ₽": "{:.2f}", "Брутто": "{:,.0f}", "Нетто": "{:,.0f}"}),
                     use_container_width=True, hide_index=True)

        fig_cal = go.Figure()
        fig_cal.add_trace(go.Bar(
            x=df_cal["Нетто"], y=df_cal["Тикер"], orientation="h",
            marker_color="#26a69a", text=df_cal["Нетто"].apply(lambda x: f"{x:,.0f} ₽"),
            textposition="outside", name="Нетто"
        ))
        fig_cal.update_layout(height=350, plot_bgcolor="white",
                              xaxis=dict(title="Дивиденды нетто, ₽", showgrid=True, gridcolor="lightgray"),
                              yaxis=dict(autorange="reversed"), margin=dict(t=30, b=30, l=30, r=60))
        st.plotly_chart(fig_cal, use_container_width=True)
        st.caption(f"Сумма нетто по календарю: {df_cal['Нетто'].sum():,.0f} ₽")
