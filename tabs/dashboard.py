from __future__ import annotations
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from core import state
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking, get_asset_color
from core.calc import get_instrument


# ============================================================
# ПАРАМЕТРЫ ДЛЯ ТЕПЛОВОЙ КАРТЫ
# ============================================================
HEATMAP_METRICS = {
    "dsi": "DSI",
    "div_yield": "Дивидендная доходность, %",
    "rel_strength": "Сила актива, %",
    "total_score": "Сумма баллов",
    "score_w": "Балл W-формации",
    "score_arsagera": "Балл Арсагера",
    "score_div": "Балл дивидендов",
    "score_dsi": "Балл DSI",
    "score_strength": "Балл силы актива",
    "score_paid_12m": "Балл выплат",
    "score_list": "Балл листинга",
    "score_in_index": "Балл индекса",
    "recommended_price": "Рекомендуемая цена, ₽",
    "div_12m": "Дивиденд 12м, ₽",
    "ars_group": "Группа Арсагера",
    "w_form": "W-формация (текст)",
}


# ============================================================
# ФИЛЬТРЫ (как в rating.py)
# ============================================================
def _apply_filters(df_all: pd.DataFrame, search, min_score, w_filter, ars_filter,
                   imoex_filter, list_filter, min_vol, sort_by) -> pd.DataFrame:
    df = df_all.copy()
    mask = pd.Series(True, index=df.index)
    if search:
        q = search.strip().upper()
        mask &= (
            df["SECID"].str.upper().str.contains(q, na=False, regex=False)
            | df["SHORTNAME"].str.upper().str.contains(q, na=False, regex=False)
        )
    if min_score > 0:
        mask &= df["total_score"] >= min_score
    if w_filter == "нет данных":
        mask &= df["w_form"] == "-"
    elif w_filter == "только с данными":
        mask &= df["w_form"] != "-"
    elif w_filter != "все":
        mask &= df["w_form"] == w_filter
    if ars_filter != "все":
        ars_map = {"Группа 1": 1, "Группа 2": 2, "Группа 3": 3, "Группа 4": 4, "Нет данных": 0}
        mask &= df["ars_group"] == ars_map[ars_filter]
    if imoex_filter != "все":
        mask &= df["in_index"] == (imoex_filter == "да")
    if list_filter != "все":
        mask &= df["LISTLEVEL"] == list_filter
    if min_vol > 0 and "VALTODAY" in df.columns:
        mask &= df["VALTODAY"] >= min_vol
    df = df[mask].copy()
    sort_map = {
        "Баллы ↓": ("total_score", False),
        "Баллы ↑": ("total_score", True),
        "Тикер": ("SECID", True),
        "Сила актива ↓": ("rel_strength", False),
        "Див. доходность ↓": ("div_yield", False),
    }
    col, asc = sort_map[sort_by]
    df = df.sort_values(col, ascending=asc).reset_index(drop=True)
    return df


# ============================================================
# РЕНДЕР ДАШБОРДА
# ============================================================
def render_dashboard(df_stocks: pd.DataFrame):
    st.subheader("Дашборд")

    df_indices = fetch_moex_indices()
    if df_stocks.empty or df_indices.empty:
        st.warning("Нет данных MOEX.")
        return

    df_stocks = df_stocks[df_stocks["PRICE"] > 0].copy()
    extreme_date = state.g("extreme_date")

    with st.spinner("Расчёт рейтинга..."):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices["SECID"] == "IMOEX"]
        imoex_curr = imoex_row["CURRENTVALUE"].values[0] if not imoex_row.empty else 0.0
        w_forms = state.g("w_formations")
        cb_rate = state.g("cb_rate")
        df_all = calc_ranking(df_stocks, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr)

    # ============================================================
    # ФИЛЬТРЫ
    # ============================================================
    st.markdown("#### Фильтры")
    fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
    with fc1:
        search = st.text_input("Поиск", placeholder="Тикер или название",
                               key="dash_search", label_visibility="collapsed")
    with fc2:
        min_score = st.number_input("Мин. балл", min_value=0, max_value=800,
                                    value=0, step=50, key="dash_min_score")
    with fc3:
        w_filter = st.selectbox("W-формация",
                                ["все", "только с данными", "вверх", "рейндж", "вниз", "нет данных"],
                                key="dash_w")
    with fc4:
        ars_filter = st.selectbox("Арсагера",
                                  ["все", "Группа 1", "Группа 2", "Группа 3", "Группа 4", "Нет данных"],
                                  key="dash_ars")
    fc5, fc6, fc7, fc8 = st.columns(4)
    with fc5:
        imoex_filter = st.selectbox("IMOEX", ["все", "да", "нет"], key="dash_imoex")
    with fc6:
        list_filter = st.selectbox("Листинг", ["все", 1, 2, 3], key="dash_list")
    with fc7:
        min_vol = st.number_input("Мин. объём, ₽", min_value=0, value=0,
                                  step=100_000, key="dash_min_vol")
    with fc8:
        sort_by = st.selectbox("Сортировка",
                               ["Баллы ↓", "Баллы ↑", "Тикер", "Сила актива ↓", "Див. доходность ↓"],
                               key="dash_sort")

    df_filtered = _apply_filters(df_all, search, min_score, w_filter, ars_filter,
                                 imoex_filter, list_filter, min_vol, sort_by)

    st.caption(f"Показано **{len(df_filtered)}** из **{len(df_all)}** бумаг")

    # ============================================================
    # ТЕПЛОВАЯ КАРТА
    # ============================================================
    st.markdown("#### Тепловая карта активов")

    c1, c2 = st.columns([1, 3])
    with c1:
        metric = st.selectbox(
            "Параметр для тепловой карты",
            options=list(HEATMAP_METRICS.keys()),
            format_func=lambda x: HEATMAP_METRICS[x],
            key="dash_heatmap_metric",
            index=list(HEATMAP_METRICS.keys()).index("total_score") if "total_score" in HEATMAP_METRICS else 0,
        )
        max_items = st.number_input("Макс. кол-во акций на карте", min_value=5, max_value=200,
                                    value=50, step=10, key="dash_max_items")
        color_scheme = st.selectbox("Цветовая схема",
                                    ["Viridis", "Plasma", "RdYlGn", "RdYlBu", "Hot", "Blues", "Greens"],
                                    key="dash_color")

    with c2:
        if df_filtered.empty:
            st.info("Нет данных для отображения.")
        else:
            df_heat = df_filtered.head(max_items).copy()
            df_heat = df_heat.sort_values(metric, ascending=False)

            if metric == "w_form":
                # Для текстового параметра — показываем цветные ячейки
                w_map = {"вверх": 2, "рейндж": 1, "вниз": 0, "-": -1}
                df_heat["w_num"] = df_heat["w_form"].map(w_map).fillna(-1)
                values = df_heat["w_num"].values
                hover_text = [f"{t}: {v}" for t, v in zip(df_heat["SECID"], df_heat["w_form"])]
                colorscale = [[0, "#F44336"], [0.5, "#2196F3"], [1, "#4CAF50"]]
                z_title = "W-форма"
            else:
                values = df_heat[metric].fillna(0).values
                hover_text = [f"{t}: {v:.2f}" for t, v in zip(df_heat["SECID"], values)]
                colorscale = color_scheme
                z_title = HEATMAP_METRICS[metric]

            fig_heat = go.Figure()
            fig_heat.add_trace(go.Heatmap(
                z=[values],
                x=df_heat["SECID"].tolist(),
                y=[""],
                colorscale=colorscale,
                hovertemplate="%{x}<br>%{text}<extra></extra>",
                text=[hover_text],
                hoverlabel=dict(bgcolor="white", font_size=12),
                showscale=True,
                colorbar=dict(title=z_title, tickformat=".2f" if metric != "w_form" else None),
                xgap=2,
                ygap=2,
            ))
            fig_heat.update_layout(
                height=180,
                margin=dict(l=10, r=10, t=10, b=40),
                xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                yaxis=dict(showticklabels=False),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_heat, use_container_width=True, key="dash_heatmap_chart")

    # Кнопка экспорта тепловой карты в PNG
    if not df_filtered.empty:
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            if st.button("📷 Сохранить тепловую карту в PNG", key="dash_save_heatmap"):
                try:
                    img_bytes = fig_heat.to_image(format="png", width=1600, height=300, scale=2)
                    st.download_button(
                        "⬇️ Скачать PNG",
                        data=img_bytes,
                        file_name=f"heatmap_{metric}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.png",
                        mime="image/png",
                        key="dash_download_heatmap",
                    )
                except Exception as e:
                    st.error(f"Ошибка экспорта: {e}. Установите kaleido: pip install kaleido")

    st.divider()

    # ============================================================
    # АНАЛИТИКА СЕКТОРОВ ПОРТФЕЛЯ
    # ============================================================
    st.markdown("#### Аналитика портфеля")

    portfolio_data = state.g("portfolio_data", [])
    if not portfolio_data:
        st.info("Портфель пуст. Загрузите Excel-файл в боковом меню.")
    else:
        port_df = pd.DataFrame(portfolio_data)
        cash = state.g("portfolio_cash", 0.0)

        # Считаем стоимость каждой позиции
        port_values = []
        for _, row in port_df.iterrows():
            t = row["Тикер"]
            avg_price = float(row["ТВХ"])
            lots = int(row["Лотов"])
            inst = get_instrument(t, df_stocks)
            current_price = inst.price if inst.price > 0 else avg_price
            lot_size = inst.lot_size if inst.lot_size > 0 else 1
            value = current_price * lots * lot_size
            sector = row.get("Сектор", "Разное")
            port_values.append({
                "Тикер": t,
                "Сектор": sector,
                "Стоимость": value,
                "Лотов": lots,
                "ТВХ": avg_price,
                "P/L %": (current_price / avg_price - 1) * 100 if avg_price > 0 else 0,
            })
        port_val_df = pd.DataFrame(port_values)

        total_stocks = port_val_df["Стоимость"].sum()
        total_portfolio = total_stocks + cash
        cash_pct = (cash / total_portfolio * 100) if total_portfolio > 0 else 0

        # --- Pie chart: распределение по секторам ---
        sector_agg = port_val_df.groupby("Сектор")["Стоимость"].sum().reset_index()
        sector_agg["Доля, %"] = (sector_agg["Стоимость"] / total_portfolio * 100)
        sector_agg = sector_agg.sort_values("Стоимость", ascending=False)

        # Добавляем кеш как отдельный сектор
        cash_row = pd.DataFrame([{"Сектор": "💰 Кеш", "Стоимость": cash, "Доля, %": cash_pct}])
        sector_agg_full = pd.concat([sector_agg, cash_row], ignore_index=True)

        fig_pie = px.pie(
            sector_agg_full,
            values="Стоимость",
            names="Сектор",
            title="Распределение портфеля по секторам",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_pie.update_traces(
            textinfo="label+percent",
            textfont_size=11,
            hovertemplate="%{label}<br>%{value:,.0f} ₽ (%{percent})<extra></extra>",
        )
        fig_pie.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))

        # --- Bar chart: P/L по секторам ---
        sector_pl = port_val_df.groupby("Сектор").apply(
            lambda g: (g["Стоимость"] - g["ТВХ"] * g["Лотов"] * g["Стоимость"] / g["Стоимость"].sum() if g["Стоимость"].sum() > 0 else 0)
        ).reset_index(name="P/L, ₽")
        # Упрощённый расчёт P/L по сектору
        sector_pl = port_val_df.groupby("Сектор").apply(
            lambda g: ((g["Стоимость"] / (1 + g["P/L %"] / 100)).sum() - g["Стоимость"].sum()) * -1
        ).reset_index(name="P/L, ₽")

        fig_bar = px.bar(
            sector_pl,
            x="Сектор",
            y="P/L, ₽",
            title="P/L по секторам, ₽",
            color="P/L, ₽",
            color_continuous_scale="RdYlGn",
        )
        fig_bar.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=40))

        c_pie, c_bar = st.columns(2)
        with c_pie:
            st.plotly_chart(fig_pie, use_container_width=True, key="dash_pie")
        with c_bar:
            st.plotly_chart(fig_bar, use_container_width=True, key="dash_bar")

        # --- Ключевые метрики портфеля ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Всего портфель", f"{total_portfolio:,.0f} ₽")
        m2.metric("Акции", f"{total_stocks:,.0f} ₽ ({(total_stocks/total_portfolio*100):.1f}%)")
        m3.metric("Кеш", f"{cash:,.0f} ₽ ({cash_pct:.1f}%)")
        total_pl = (port_val_df["Стоимость"] - port_val_df["ТВХ"] * port_val_df["Лотов"]).sum()
        m4.metric("Общий P/L", f"{total_pl:+,.0f} ₽")

        # Кнопка экспорта аналитики в PNG
        if st.button("📷 Сохранить аналитику портфеля в PNG", key="dash_save_analytics"):
            try:
                combined = make_subplots(rows=1, cols=2, specs=[[{"type": "pie"}, {"type": "xy"}]])
                for trace in fig_pie.data:
                    combined.add_trace(trace, row=1, col=1)
                for trace in fig_bar.data:
                    combined.add_trace(trace, row=1, col=2)
                combined.update_layout(height=400, title_text="Аналитика портфеля")
                img_bytes = combined.to_image(format="png", width=1400, height=500, scale=2)
                st.download_button(
                    "⬇️ Скачать PNG",
                    data=img_bytes,
                    file_name=f"portfolio_analytics_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.png",
                    mime="image/png",
                    key="dash_download_analytics",
                )
            except Exception as e:
                st.error(f"Ошибка экспорта: {e}. Установите kaleido: pip install kaleido")

    st.divider()

    # ============================================================
    # ТАБЛИЦА РЕЙТИНГА С ЭКСПОРТОМ В PNG
    # ============================================================
    st.markdown("#### Таблица рейтинга (с фильтрами)")

    if df_filtered.empty:
        st.info("Нет данных для отображения.")
    else:
        display_df = df_filtered.head(100).copy()
        display_df["№"] = range(1, len(display_df) + 1)
        display_df["in_index_str"] = display_df["in_index"].map({True: "да", False: "нет"})

        table_data = pd.DataFrame({
            "№": display_df["№"],
            "Тикер": display_df["SECID"],
            "Название": display_df["SHORTNAME"],
            "W": display_df["w_form"],
            "Арс": display_df["ars_group"],
            "Индекс": display_df["in_index_str"],
            "Сила": display_df["rel_strength"].round(2),
            "Див.дох%": display_df["div_yield"].round(2),
            "DSI": display_df["dsi"].round(2),
            "Листинг": display_df["LISTLEVEL"].astype(int),
            "Баллы": display_df["total_score"].astype(int),
            "Реком.цена": display_df["recommended_price"].round(2),
        })

        # Plotly table для PNG экспорта
        fig_table = go.Figure(data=[go.Table(
            header=dict(
                values=list(table_data.columns),
                fill_color="#1f2937",
                font=dict(color="white", size=11),
                align="center",
            ),
            cells=dict(
                values=[table_data[col].tolist() for col in table_data.columns],
                fill_color=[
                    ["#4CAF50" if v == "вверх" else "#2196F3" if v == "рейндж"
                     else "#F44336" if v == "вниз" else "white"
                     for v in table_data["W"].tolist()],
                ] + [["white"] * len(table_data)] * (len(table_data.columns) - 1),
                font=dict(size=10),
                align="center",
                height=28,
            ),
        )])
        fig_table.update_layout(
            height=40 + 30 * len(table_data),
            margin=dict(l=10, r=10, t=10, b=10),
        )

        st.dataframe(
            table_data.style.apply(
                lambda row: [
                    "background-color: #4CAF50; color: white;" if row["W"] == "вверх"
                    else "background-color: #2196F3; color: white;" if row["W"] == "рейндж"
                    else "background-color: #F44336; color: white;" if row["W"] == "вниз"
                    else ""
                ] + [""] * (len(row) - 1),
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
            height=min(600, 40 + 35 * len(table_data)),
        )

        if st.button("📷 Сохранить таблицу рейтинга в PNG", key="dash_save_table"):
            try:
                img_bytes = fig_table.to_image(format="png", width=1800,
                                                height=40 + 30 * len(table_data), scale=2)
                st.download_button(
                    "⬇️ Скачать PNG",
                    data=img_bytes,
                    file_name=f"rating_table_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.png",
                    mime="image/png",
                    key="dash_download_table",
                )
            except Exception as e:
                st.error(f"Ошибка экспорта: {e}. Установите kaleido: pip install kaleido")

    st.divider()

    # ============================================================
    # СВОДНЫЙ ДАШБОРД (все графики вместе)
    # ============================================================
    st.markdown("#### Сводный дашборд")

    if st.button("📷 Сохранить весь дашборд в PNG", key="dash_save_all"):
        try:
            # Создаём комбинированный график
            fig_all = make_subplots(
                rows=3, cols=1,
                specs=[[{"type": "heatmap"}],
                       [{"type": "pie"}],
                       [{"type": "xy"}]],
                row_heights=[0.3, 0.35, 0.35],
                vertical_spacing=0.08,
            )

            # 1. Тепловая карта
            if not df_filtered.empty:
                df_h = df_filtered.head(30).sort_values("total_score", ascending=False)
                z_vals = [df_h["total_score"].fillna(0).values]
                fig_all.add_trace(go.Heatmap(
                    z=z_vals, x=df_h["SECID"].tolist(), y=["Баллы"],
                    colorscale="Viridis", showscale=False,
                ), row=1, col=1)

            # 2. Pie секторов
            if portfolio_data:
                for trace in fig_pie.data:
                    fig_all.add_trace(trace, row=2, col=1)

            # 3. Bar P/L
            if portfolio_data:
                for trace in fig_bar.data:
                    fig_all.add_trace(trace, row=3, col=1)

            fig_all.update_layout(
                height=1100,
                title_text=f"Дашборд портфеля — {pd.Timestamp.now().strftime('%d.%m.%Y %H:%M')}",
                margin=dict(l=40, r=40, t=60, b=40),
            )

            img_bytes = fig_all.to_image(format="png", width=1400, height=1200, scale=2)
            st.download_button(
                "⬇️ Скачать полный дашборд PNG",
                data=img_bytes,
                file_name=f"dashboard_full_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.png",
                mime="image/png",
                key="dash_download_all",
            )
        except Exception as e:
            st.error(f"Ошибка экспорта: {e}. Установите kaleido: pip install kaleido")
