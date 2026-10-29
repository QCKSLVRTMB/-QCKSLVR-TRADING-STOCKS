from __future__ import annotations
import pandas as pd
import numpy as np
import streamlit as st

from core import charts, state
from core.calc import get_instrument, calculate_volume_profile, get_volume_colors
from core.config import INTERVALS, TOOLS
from core.market import fetch_moex_candles
from ui.theme import seg

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
            snapped.append([str(matching_indices[idx]), float(p_val)])
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
                snapped.append([str(exact_idx), float(p_val)])
            else:
                snapped.append([str(p_str), float(p_val)])
    return snapped

def render_trade_planner(ticker: str, df_stocks: pd.DataFrame):
    inst = get_instrument(ticker, df_stocks)
    tdata = state.ticker(ticker)
    mobile = state.g("mobile_view")
    
    st.subheader(f"{ticker} — {inst.name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Цена", f"{inst.price:.2f} ₽", f"{inst.change_pct:+.2f}%" if hasattr(inst, 'change_pct') else None)
    c2.metric("Лот", f"{inst.lot_size} шт.")
    c3.metric("Стоимость лота", f"{inst.lot_value:.2f} ₽")
    c4.metric("Листинг", f"{inst.list_level} ур.")

    st.markdown("#### Параметры сделки")
    c_sl, c_tp = st.columns(2)
    with c_sl:
        buy_level = st.number_input("Уровень покупок (SL)", value=float(tdata.get("buy_level") or 0.0), step=float(inst.min_step), format=f"%.{inst.decimals}f", key=f"buy_{ticker}")
        tdata["buy_level"] = float(buy_level) if buy_level > 0 else None
    with c_tp:
        sell_level = st.number_input("Уровень продаж (TP)", value=float(tdata.get("sell_level") or 0.0), step=float(inst.min_step), format=f"%.{inst.decimals}f", key=f"sell_{ticker}")
        tdata["sell_level"] = float(sell_level) if sell_level > 0 else None

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
        tdata["entries"] = [
            {"price": float(r["Цена"]), "qty": int(r["Лотов"]), "note": str(r["Комментарий"])} 
            for _, r in edited.iterrows() if not r.get("Lock", False)
        ]
        
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

    st.markdown("#### Графики рынка")
    c_tog1, c_tog2 = st.columns(2)
    with c_tog1:
        show_clusters = st.toggle("Кластеры объемов (M10)", value=tdata.get("show_clusters", False), key=f"clu_{ticker}")
        tdata["show_clusters"] = show_clusters
    with c_tog2:
        show_custom_clusters = st.toggle("Диапазон кластеров (D1)", value=tdata.get("show_custom_clusters", False), key=f"clu_custom_{ticker}")
        tdata["show_custom_clusters"] = show_custom_clusters

    clusters_data = []
    custom_clusters_data = []
    
    if show_clusters or show_custom_clusters:
        overlap_pct = st.slider("Порог отсечения кластеров", 10, 100, tdata.get("cluster_threshold", 50), 5, key=f"clu_bins_{ticker}")
        tdata["cluster_threshold"] = int(overlap_pct)
        
        # 1. Автоматические кластеры от канала
        if show_clusters:
            d1_pts = tdata["charts"]["D1"].get("channel", [])
            if len(d1_pts) == 3:
                cluster_start_time = pd.to_datetime(d1_pts[2][0])
                df_m10 = fetch_moex_candles(ticker, interval=10, days_back=60)
                if not df_m10.empty:
                    # Рассчитываем цвета на полном df_m10 для корректного скользящего среднего
                    all_colors = get_volume_colors(df_m10, "M10")
                    mask = df_m10.index >= cluster_start_time
                    df_slice = df_m10[mask]
                    colors_slice = np.array(all_colors)[mask]
                    
                    if not df_slice.empty:
                        clusters_data = calculate_volume_profile(df_slice, tf_name="M10", threshold_pct=overlap_pct, colors=colors_slice)
                        if not clusters_data:
                            st.caption("В зоне канала нет аномальных объёмов M10.")

        # 2. Ручные кластеры (диапазон)
        if show_custom_clusters:
            cr_pts = tdata["charts"]["D1"].get("cluster_range", [])
            if len(cr_pts) == 2:
                t1 = pd.to_datetime(cr_pts[0][0])
                t2 = pd.to_datetime(cr_pts[1][0])
                t_start, t_end = min(t1, t2), max(t1, t2)
                
                df_m10 = fetch_moex_candles(ticker, interval=10, days_back=730)
                if not df_m10.empty:
                    all_colors = get_volume_colors(df_m10, "M10")
                    mask = (df_m10.index >= t_start) & (df_m10.index <= t_end)
                    df_slice = df_m10[mask]
                    colors_slice = np.array(all_colors)[mask]
                    
                    if not df_slice.empty:
                        custom_clusters_data = calculate_volume_profile(df_slice, tf_name="M10", threshold_pct=overlap_pct, colors=colors_slice)
                        if not custom_clusters_data:
                            st.caption("В выбранном диапазоне нет аномальных объёмов M10.")
                    else:
                        st.caption("Нет M10 данных в выбранном диапазоне дат.")

    chart_tabs = st.tabs([cfg["label"] for cfg in INTERVALS.values()])
    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, buy_level, sell_level, clusters_data, custom_clusters_data)

    state.autosave()

def _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, buy_level, sell_level, clusters_data, custom_clusters_data):
    chart_data = tdata["charts"][tf_name]

    if tf_name == "W": available_tools = ["channel", "fib_d1"]
    elif tf_name == "D1": available_tools = ["channel", "fib_d1", "cluster_range"]
    elif tf_name == "H1": available_tools = ["zigzag", "fib_h1"]
    else: available_tools = ["zigzag"]

    tool_labels = {"cluster_range": "Диапазон кластеров"}

    c1, c2 = st.columns([1, 1])
    with c1:
        tool = seg("Инструмент", available_tools, key=f"tool_{ticker}_{tf_name}", default=available_tools[0], fmt=lambda x: tool_labels.get(x, TOOLS.get(x, x))) or available_tools[0]
    with c2:
        cc1, cc2 = st.columns(2)
        show_tools = cc1.toggle("Разметка", value=chart_data.get("show_tools", True), key=f"tools_{ticker}_{tf_name}")
        chart_data["show_tools"] = bool(show_tools)
        show_position = cc1.toggle("Позиция", value=chart_data.get("show_position", True), key=f"pos_{ticker}_{tf_name}")
        chart_data["show_position"] = bool(show_position)
        show_info = cc2.toggle("Информация", value=chart_data.get("show_info", True), key=f"info_{ticker}_{tf_name}")
        chart_data["show_info"] = bool(show_info)

    if tf_name == "W": target_tool = tool if tool == "channel" else "fib"
    elif tf_name == "D1": target_tool = tool if tool in ["channel", "cluster_range"] else "fib"
    elif tf_name == "H1": target_tool = "zigzag" if tool == "zigzag" else "fib"
    else: target_tool = "zigzag"

    if target_tool not in chart_data: chart_data[target_tool] = []

    b1, b2 = st.columns(2)
    if b1.button("Отменить", key=f"undo_{ticker}_{tf_name}", use_container_width=True):
        if chart_data.get(target_tool): chart_data[target_tool].pop(); state.autosave(force=True); st.rerun()
    if b2.button("Очистить", key=f"clr_{ticker}_{tf_name}", use_container_width=True):
        chart_data[target_tool] = []; state.autosave(force=True); st.rerun()

    df = fetch_moex_candles(ticker, cfg["interval"], cfg["days_back"])
    if df.empty:
        st.warning("Нет данных MOEX.")
        return

    d1_pts = tdata["charts"]["D1"].get("channel", [])
    h1_zig = tdata["charts"]["H1"].get("zigzag", [])
    zoom_start = None
    if tf_name == "H1" and len(d1_pts) == 3: zoom_start = d1_pts[2][0]
    elif tf_name == "M10" and len(h1_zig) >= 4: zoom_start = h1_zig[-4][0]

    default_bars = 150
    if zoom_start:
        try:
            z_time = pd.to_datetime(zoom_start)
            filtered_df = df.loc[z_time:]
            view = df.tail(default_bars).copy() if len(filtered_df) < 10 else filtered_df.copy()
        except Exception:
            view = df.tail(default_bars).copy()
    else:
        view = df.tail(default_bars).copy()

    chart_key = f"chart_{ticker}_{tf_name}"
    click = charts.capture_click(chart_key)
    pts = chart_data.get(target_tool, [])

    if click:
        x, y = click
        y = float(inst.round_price(y))
        bar = view.iloc[view.index.get_indexer([pd.to_datetime(x)], method='nearest')[0]]
        new_pts = pts.copy()
        max_pts = 3 if tool == "channel" else (2 if tool in ["fib", "cluster_range"] else None)

        if max_pts is None or len(new_pts) < max_pts:
            if tool == "channel":
                if len(new_pts) == 0: new_pts.append([str(bar.name), float(y)])
                elif len(new_pts) == 1:
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
                        new_pts = [[str(t_start), float(y_start)], [str(t_mid), float(y_mid)], [str(t_end), float(y_end)]]
            elif tool == "cluster_range":
                if len(new_pts) == 0: new_pts.append([str(bar.name), float(bar['Low'])])
                elif len(new_pts) == 1: new_pts.append([str(bar.name), float(bar['High'])])
            elif "zigzag" in tool:
                if new_pts and pd.to_datetime(new_pts[-1][0]) == bar.name:
                    last_y = new_pts[-1][1]
                    new_pts[-1] = [str(bar.name), float(bar['Low']) if last_y == bar['High'] else float(bar['High'])]
                elif not new_pts:
                    current_price = float(view.iloc[-1]['Close'])
                    snapped_y = float(bar['Low']) if (float(bar['High'])+float(bar['Low']))/2 < current_price else float(bar['High'])
                    new_pts.append([str(bar.name), float(snapped_y)])
                elif len(new_pts) == 1:
                    snapped_y = float(bar['High']) if y > new_pts[0][1] else float(bar['Low'])
                    new_pts.append([str(bar.name), float(snapped_y)])
                else:
                    is_last_high = new_pts[-1][1] == view.loc[pd.to_datetime(new_pts[-1][0]), 'High']
                    snapped_y = float(bar['Low']) if is_last_high else float(bar['High'])
                    new_pts.append([str(bar.name), float(snapped_y)])
            else:  # fib
                if len(new_pts) == 0:
                    new_pts.append([str(bar.name), float(bar['High']) if abs(y-float(bar['High']))<abs(y-float(bar['Low'])) else float(bar['Low'])])
                elif len(new_pts) == 1:
                    if y > new_pts[0][1]:
                        new_pts[0] = [new_pts[0][0], float(view.loc[pd.to_datetime(new_pts[0][0]), 'Low'])]
                        new_pts.append([str(bar.name), float(bar['High'])])
                    else:
                        new_pts[0] = [new_pts[0][0], float(view.loc[pd.to_datetime(new_pts[0][0]), 'High'])]
                        new_pts.append([str(bar.name), float(bar['Low'])])

            if new_pts != pts:
                chart_data[target_tool] = new_pts
                state.autosave(force=True)
                st.rerun()

    if tf_name == "W":
        w_ch_s, w_fib_s = snap_points(tdata["charts"]["W"]["channel"], view), snap_points(tdata["charts"]["W"]["fib"], view)
        d1_ch_s, d1_fib_s, d1_cr_s, h1_zig_s, h1_fib_s, m10_zig_s = [], [], [], [], [], []
    elif tf_name == "D1":
        w_ch_s, w_fib_s = tdata["charts"]["W"]["channel"], tdata["charts"]["W"]["fib"]
        d1_ch_s = snap_points(tdata["charts"]["D1"]["channel"], view)
        d1_fib_s = snap_points(tdata["charts"]["D1"]["fib"], view)
        d1_cr_s = snap_points(tdata["charts"]["D1"].get("cluster_range", []), view)
        h1_zig_s, h1_fib_s, m10_zig_s = tdata["charts"]["H1"]["zigzag"], tdata["charts"]["H1"]["fib"], tdata["charts"]["M10"]["zigzag"]
    elif tf_name == "H1":
        w_ch_s, w_fib_s = tdata["charts"]["W"]["channel"], tdata["charts"]["W"]["fib"]
        d1_ch_s, d1_fib_s = tdata["charts"]["D1"]["channel"], tdata["charts"]["D1"]["fib"]
        d1_cr_s = tdata["charts"]["D1"].get("cluster_range", [])
        h1_zig_s = snap_points(tdata["charts"]["H1"]["zigzag"], view)
        h1_fib_s = snap_points(tdata["charts"]["H1"]["fib"], view)
        m10_zig_s = tdata["charts"]["M10"]["zigzag"]
    else: # M10
        w_ch_s, w_fib_s = tdata["charts"]["W"]["channel"], tdata["charts"]["W"]["fib"]
        d1_ch_s, d1_fib_s = tdata["charts"]["D1"]["channel"], tdata["charts"]["D1"]["fib"]
        d1_cr_s = tdata["charts"]["D1"].get("cluster_range", [])
        h1_zig_s, h1_fib_s = tdata["charts"]["H1"]["zigzag"], tdata["charts"]["H1"]["fib"]
        m10_zig_s = snap_points(tdata["charts"]["M10"]["zigzag"], view)

    fig = charts.build_figure(view, tf_name=tf_name, title=f"{ticker} — {tf_name}", decimals=inst.decimals, mobile=mobile, show_info=show_info)

    time_buffer = pd.Timedelta(days=10) if tf_name in ["D1", "W"] else (pd.Timedelta(hours=12) if tf_name == "H1" else pd.Timedelta(hours=2))
    x_left = view.index[0]
    x_right = view.index[-1] + time_buffer

    if clusters_data: charts.draw_clusters(fig, clusters_data, x_left, x_right, color="orange")
    if custom_clusters_data: charts.draw_clusters(fig, custom_clusters_data, x_left, x_right, color="blue")

    if show_tools:
        if w_ch_s: charts.draw_channel(fig, w_ch_s, x_right, color="purple")
        if w_fib_s: charts.draw_fib(fig, w_fib_s, x_left, x_right, "purple", "0.5 W")
        if d1_ch_s: charts.draw_channel(fig, d1_ch_s, x_right, color="blue")
        if d1_fib_s: charts.draw_fib(fig, d1_fib_s, x_left, x_right, "blue", "0.5 D1")
        if h1_fib_s: charts.draw_fib(fig, h1_fib_s, x_left, x_right, "green", "0.5 H1")
        if d1_cr_s and len(d1_cr_s) == 2: charts.draw_zigzag(fig, d1_cr_s, "#2196F3", "Диапазон кластеров")
        if h1_zig_s: charts.draw_zigzag(fig, h1_zig_s, "#26a69a", "Тенденция (H1)")
        if m10_zig_s and tf_name in ["H1", "M10"]: charts.draw_zigzag(fig, m10_zig_s, "#ef5350", "Зигзаг (M10)")

    if show_position:
        charts.draw_trade_visuals(fig, buy_level, sell_level, x_left, x_right, inst.decimals)

    st.plotly_chart(fig, use_container_width=True, key=chart_key, on_select="rerun", selection_mode="points", config=charts.PLOT_CONFIG)
    st.caption(f"Диапазон отображения: {view.index[0].strftime('%d.%m.%Y %H:%M')} – {view.index[-1].strftime('%d.%m.%Y %H:%M')} · Баров: {len(view)}")
