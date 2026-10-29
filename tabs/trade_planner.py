from __future__ import annotations
import pandas as pd
import streamlit as st

from core import charts, state
from core.calc import get_instrument, calculate_volume_profile
from core.config import INTERVALS, TOOLS
from core.market import fetch_moex_candles

def snap_points(pts, df):
    if not pts or df.empty: return pts
    snapped = []
    for p_str, p_val in pts:
        try:
            t = pd.to_datetime(p_str)
        except Exception:
            snapped.append([p_str, p_val])
            continue
        
        tol = 1e-4 * max(abs(p_val), 1.0)
        mask_high = (df['High'] - p_val).abs() <= tol
        mask_low = (df['Low'] - p_val).abs() <= tol
        matching_indices = df.index[mask_high | mask_low]
        
        if len(matching_indices) > 0:
            idx = matching_indices.get_indexer([t], method='nearest')[0]
            snapped.append([str(matching_indices[idx]), p_val])
        else:
            idx = df.index.get_indexer([t], method='nearest')[0]
            if idx >= 0:
                bar = df.iloc[idx]
                is_high = abs(p_val - bar['High']) <= abs(p_val - bar['Low'])
                start = max(0, idx - 1000)
                end = min(len(df) - 1, idx + 1000)
                sub_df = df.iloc[start:end+1]
                if is_high: exact_idx = (sub_df['High'] - p_val).abs().idxmin()
                else: exact_idx = (sub_df['Low'] - p_val).abs().idxmin()
                snapped.append([str(exact_idx), p_val])
            else:
                snapped.append([p_str, p_val])
    return snapped

def render_trade_planner(ticker: str, df_stocks: pd.DataFrame):
    inst = get_instrument(ticker, df_stocks)
    tdata = state.ticker(ticker)
    mobile = state.g("mobile_view")
    
    # Заголовок
    st.subheader(f"{ticker} — {inst.name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Цена", f"{inst.price:.2f} ₽", f"{inst.change_pct:+.2f}%" if hasattr(inst, 'change_pct') else None)
    c2.metric("Лот", f"{inst.lot_size} шт.")
    c3.metric("Стоимость лота", f"{inst.lot_value:.2f} ₽")
    c4.metric("Листинг", f"{inst.list_level} ур.")

    # Параметры сделки
    st.markdown("#### Параметры сделки")
    c_sl, c_tp = st.columns(2)
    with c_sl:
        buy_level = st.number_input("Уровень покупок (SL)", value=float(tdata.get("buy_level") or 0.0), step=float(inst.min_step), format=f"%.{inst.decimals}f", key=f"buy_{ticker}")
        tdata["buy_level"] = buy_level if buy_level > 0 else None
    with c_tp:
        sell_level = st.number_input("Уровень продаж (TP)", value=float(tdata.get("sell_level") or 0.0), step=float(inst.min_step), format=f"%.{inst.decimals}f", key=f"sell_{ticker}")
        tdata["sell_level"] = sell_level if sell_level > 0 else None

    # Расчет усреднения
    st.markdown("#### Расчет усреднения (ТВХ)")
    if "entries" not in tdata: tdata["entries"] = []
    
    port_data = state.g("portfolio_data", {}).get(ticker, {})
    rows = []
    if port_data:
        rows.append({"Цена": port_data["avg_price"], "Лотов": port_data["lots"], "Комментарий": "Из портфеля", "Lock": True})
    for e in tdata["entries"]:
        rows.append({"Цена": e["price"], "Лотов": e["qty"], "Комментарий": e.get("note", ""), "Lock": False})
        
    df_entries = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Цена", "Лотов", "Комментарий", "Lock"])
    
    edited = st.data_editor(
        df_entries, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Цена": st.column_config.NumberColumn(format=f"%.{inst.decimals}f", step=inst.min_step),
            "Лотов": st.column_config.NumberColumn(step=1),
            "Комментарий": st.column_config.TextColumn(),
            "Lock": None
        },
        disabled=["Цена", "Лотов"] if port_data else []
    )
    
    if not edited.empty and "Цена" in edited.columns and "Лотов" in edited.columns:
        tdata["entries"] = [{"price": r["Цена"], "qty": int(r["Лотов"]), "note": r["Комментарий"]} for _, r in edited.iterrows() if not r.get("Lock", False)]
        
        total_lots = edited["Лотов"].sum()
        total_cost = (edited["Цена"] * edited["Лотов"] * inst.lot_size).sum()
        
        if total_lots > 0:
            avg_price = total_cost / (total_lots * inst.lot_size)
            st.metric("Средняя цена (ТВХ)", f"{avg_price:.2f} ₽")
            
            m1, m2 = st.columns(2)
            if sell_level > 0:
                m1.metric("Доходность до продажи", f"{(sell_level / avg_price - 1) * 100:.2f}%")
            if buy_level > 0:
                m2.metric("Риск до покупки", f"{(1 - buy_level / avg_price) * 100:.2f}%")

    # === БЛОК ГРАФИКОВ ===
    st.markdown("#### Графики рынка")
    
    # Кластеры
    show_clusters = st.toggle("Кластеры объемов (M10)", value=tdata.get("show_clusters", False), key=f"clu_{ticker}")
    tdata["show_clusters"] = show_clusters
    clusters_data = []
    if show_clusters:
        overlap_pct = st.slider("Порог отсечения кластеров", 10, 100, tdata.get("cluster_threshold", 50), 5, key=f"clu_bins_{ticker}")
        tdata["cluster_threshold"] = overlap_pct
        
        # Безопасное получение списка точек
        d1_pts = tdata["charts"]["D1"].get("cluster_range", [])
        if len(d1_pts) == 2:
            t_start = pd.to_datetime(min(d1_pts[0][0], d1_pts[1][0]))
            df_m10 = fetch_moex_candles(ticker, interval=10, days_back=730)
            if not df_m10.empty:
                clusters_data = calculate_volume_profile(df_m10.loc[t_start:], tf_name="M10", threshold_pct=overlap_pct)

    chart_tabs = st.tabs([cfg["label"] for cfg in INTERVALS.values()])
    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, buy_level, sell_level, clusters_data)

    state.autosave()

def _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, buy_level, sell_level, clusters_data):
    chart_data = tdata["charts"][tf_name]
    color = "purple" if tf_name == "W" else "blue"

    # Выбор инструментов
    if tf_name == "W": available_tools = ["channel", "fib_d1", "cluster_range"]
    elif tf_name == "D1": available_tools = ["channel", "fib_d1", "cluster_range"]
    elif tf_name == "H1": available_tools = ["zigzag", "fib_h1"]
    else: available_tools = ["zigzag"]

    c1, c2 = st.columns([1, 1])
    with c1:
        tool = st.selectbox("Инструмент", available_tools, format_func=lambda x: TOOLS.get(x, x), key=f"tool_{ticker}_{tf_name}")
    
    # Кнопки управления
    b1, b2 = st.columns(2)
    if b1.button("Отменить", key=f"undo_{ticker}_{tf_name}", use_container_width=True):
        if chart_data.get(tool): chart_data[tool].pop(); state.autosave(force=True); st.rerun(scope="fragment")
    if b2.button("Очистить", key=f"clr_{ticker}_{tf_name}", use_container_width=True):
        chart_data[tool] = []; state.autosave(force=True); st.rerun(scope="fragment")

    df = fetch_moex_candles(ticker, cfg["interval"], cfg["days_back"])
    if df.empty:
        st.warning("Нет данных MOEX.")
        return

    view = df.tail(150).copy()
    chart_key = f"chart_{ticker}_{tf_name}"
    
    # Обработка кликов
    click = charts.capture_click(chart_key)
    pts = chart_data.get(tool, [])
    if click:
        x, y = click
        y = inst.round_price(y)
        bar = view.iloc[view.index.get_indexer([pd.to_datetime(x)], method='nearest')[0]]
        new_pts = pts.copy()
        max_pts = 3 if tool == "channel" else 2

        if len(new_pts) < max_pts:
            if tool == "channel":
                if len(new_pts) == 0: new_pts.append([str(bar.name), y])
                elif len(new_pts) == 1:
                    # Автодостройка канала
                    first_time = pd.to_datetime(new_pts[0][0])
                    second_time = pd.to_datetime(bar.name)
                    t_start, t_end = min(first_time, second_time), max(first_time, second_time)
                    view_period = view.loc[t_start:t_end]
                    if not view_period.empty:
                        is_up = y > new_pts[0][1]
                        if is_up:
                            y_start, y_end = float(view.loc[t_start, 'Low']), float(view.loc[t_end, 'Low'])
                            t_mid = view_period['High'].idxmax(); y_mid = float(view_period.loc[t_mid, 'High'])
                        else:
                            y_start, y_end = float(view.loc[t_start, 'High']), float(view.loc[t_end, 'High'])
                            t_mid = view_period['Low'].idxmin(); y_mid = float(view_period.loc[t_mid, 'Low'])
                        new_pts = [[str(t_start), y_start], [str(t_mid), y_mid], [str(t_end), y_end]]
            else: # cluster_range или fib
                if len(new_pts) == 0: new_pts.append([str(bar.name), y])
                elif len(new_pts) == 1: new_pts.append([str(bar.name), y])

            if new_pts != pts:
                chart_data[tool] = new_pts
                state.autosave(force=True)
                st.rerun(scope="fragment")

    fig = charts.build_figure(view, tf_name=tf_name, title=f"{ticker} — {tf_name}", decimals=inst.decimals, mobile=mobile)
    x_left, x_right = view.index[0], view.index[-1] + pd.Timedelta(days=5)

    if clusters_data:
        charts.draw_clusters(fig, clusters_data, x_left, x_right, color="orange")

    # Отрисовка разметки
    if chart_data.get("channel"): charts.draw_channel(fig, snap_points(chart_data["channel"], view), x_right, color=color)
    if chart_data.get("fib"): charts.draw_fib(fig, snap_points(chart_data["fib"], view), x_left, x_right, color, "0.5 Fib")
    if chart_data.get("zigzag"): charts.draw_zigzag(fig, snap_points(chart_data["zigzag"], view), "#26a69a", "Зигзаг")
    if chart_data.get("cluster_range"): charts.draw_zigzag(fig, snap_points(chart_data["cluster_range"], view), "#2196F3", "Диапазон")

    charts.draw_trade_visuals(fig, buy_level, sell_level, x_left, x_right, inst.decimals)

    st.plotly_chart(fig, use_container_width=True, key=chart_key, on_select="rerun", selection_mode="points", config=charts.PLOT_CONFIG)
