from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from core import state
from core.market import fetch_moex_stocks, fetch_many_dividends


def render_portfolio(df_stocks: pd.DataFrame):
    """Вкладка «Портфель»: карточки-сводка + таблица с расчётами."""
    name = state.g("portfolio_name", "Портфель")
    positions = state.g("portfolio_positions", [])

    st.subheader(f"📁 {name}")

    if not positions:
        st.info(
            "**Загрузите Excel-файл портфеля в боковом меню.**\n\n"
            "В файле достаточно трёх колонок:\n"
            "- **Тикер** — например `LKOH`\n"
            "- **ТВХ** (или «Средняя цена») — цена покупки\n"
            "- **Лотов** (или «Количество лотов») — целое число\n\n"
            "Всё остальное (стоимость, P/L, доля, дивиденды, рекоменд. цена) "
            "считается автоматически."
        )
        return

    if df_stocks is None or df_stocks.empty:
        st.warning("Нет данных MOEX — расчёт невозможен.")
        return

    tickers = [p["ticker"] for p in positions]
    with st.spinner("Загрузка дивидендов..."):
        divs = fetch_many_dividends(tickers)

    cb_rate = float(state.g("cb_rate", 14.0))
    tax_rate = float(state.g("tax_rate", 13.0))

    # ---------- Расчёт по каждой позиции ----------
    rows = []
    for p in positions:
        tk = p["ticker"]
        tvh = float(p["tvh"])
        qty = int(p["qty"])

        m = df_stocks[df_stocks["SECID"] == tk]
        if m.empty:
            continue
        r = m.iloc[0]
        lot = int(r["LOTSIZE"] or 1)
        price = float(r["PRICE"])
        list_level = int(r["LISTLEVEL"] or 0)

        shares = qty * lot
        invested = tvh * shares
        market_val = price * shares
        pnl = market_val - invested
        pnl_pct = (price / tvh - 1) * 100 if tvh > 0 else 0.0

        div_per_share = float(divs.get(tk, {}).get("div_12m", 0) or 0)
        div_total = div_per_share * shares
        div_yield_tvh = div_per_share / tvh * 100 if tvh > 0 else 0
        div_yield_market = div_per_share / price * 100 if price > 0 else 0
        div_net = div_total * (1 - tax_rate / 100)
        recommended = div_per_share / (cb_rate / 100) if div_per_share > 0 and cb_rate > 0 else 0

        rows.append({
            "Тикер": tk,
            "Название": r["SHORTNAME"],
            "Лотов": qty,
            "Акций": shares,
            "ТВХ": tvh,
            "Цена": price,
            "Стоимость": invested,
            "Рынок": market_val,
            "P/L ₽": pnl,
            "P/L %": pnl_pct,
            "Доля %": 0.0,
            "Див/акц": div_per_share,
            "Див 12м": div_total,
            "Див нетто": div_net,
            "Див.дох. к ТВХ %": div_yield_tvh,
            "Див.дох. к рынку %": div_yield_market,
            "Рек. макс. цена": recommended,
            "Листинг": list_level,
        })

    if not rows:
        st.warning("Не удалось сопоставить ни одну позицию с ISS — "
                   "проверьте, что тикеры корректные (LKOH, SBER, GAZP…).")
        return

    df = pd.DataFrame(rows)

    total_market = df["Рынок"].sum()
    df["Доля %"] = (df["Рынок"] / total_market * 100) if total_market > 0 else 0

    # ---------- Карточки-сводка ----------
    total_invested = df["Стоимость"].sum()
    total_pnl = total_market - total_invested
    total_pnl_pct = (total_market / total_invested - 1) * 100 if total_invested > 0 else 0
    total_div = df["Див 12м"].sum()
    total_div_net = df["Див нетто"].sum()
    avg_div_yield_tvh = (total_div / total_invested * 100) if total_invested > 0 else 0
    avg_div_yield_market = (total_div / total_market * 100) if total_market > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Стоимость портфеля",
        f"{total_market:,.0f} ₽".replace(",", " "),
        delta=f"{total_pnl_pct:+.2f}%",
    )
    c2.metric("Вложено (по ТВХ)", f"{total_invested:,.0f} ₽".replace(",", " "))
    c3.metric(
        "P/L",
        f"{total_pnl:+,.0f} ₽".replace(",", " "),
        delta_color="normal",
    )
    c4.metric(
        "Дивиденды 12м (брутто)",
        f"{total_div:,.0f} ₽".replace(",", " "),
        delta=f"нетто {total_div_net:,.0f} ₽".replace(",", " "),
    )

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Позиций", f"{len(df)}")
    c6.metric("Ср. див. дох. к ТВХ", f"{avg_div_yield_tvh:.2f}%")
    c7.metric("Ср. див. дох. к рынку", f"{avg_div_yield_market:.2f}%")
    top = df.iloc[df["Рынок"].argmax()]
    c8.metric("Крупнейшая", f"{top['Тикер']}", delta=f"{top['Доля %']:.1f}%")

    st.divider()

    # ---------- Сортировка и отображение ----------
    fc1, fc2 = st.columns([2, 1])
    with fc1:
        sort_key = st.selectbox(
            "Сортировка",
            ["Рынок ↓", "P/L % ↓", "P/L % ↑", "Див.дох. к ТВХ % ↓", "Доля % ↓", "Тикер"],
            key="port_sort",
            label_visibility="collapsed",
        )
    with fc2:
        show_all = st.checkbox("Все колонки", value=False, key="port_show_all")

    sort_map = {
        "Рынок ↓":            ("Рынок",               False),
        "P/L % ↓":            ("P/L %",               False),
        "P/L % ↑":            ("P/L %",               True),
        "Див.дох. к ТВХ % ↓": ("Див.дох. к ТВХ %",    False),
        "Доля % ↓":           ("Доля %",              False),
        "Тикер":              ("Тикер",               True),
    }
    col, asc = sort_map[sort_key]
    df = df.sort_values(col, ascending=asc).reset_index(drop=True)
    df.insert(0, "№", df.index + 1)

    if show_all:
        cols = [
            "№", "Тикер", "Название", "Лотов", "Акций", "ТВХ", "Цена",
            "Стоимость", "Рынок", "P/L ₽", "P/L %", "Доля %",
            "Див/акц", "Див 12м", "Див нетто",
            "Див.дох. к ТВХ %", "Див.дох. к рынку %",
            "Рек. макс. цена", "Листинг",
        ]
    else:
        cols = [
            "№", "Тикер", "Название", "Лотов", "ТВХ", "Цена",
            "Рынок", "P/L ₽", "P/L %", "Доля %",
            "Див 12м", "Див.дох. к ТВХ %", "Рек. макс. цена",
        ]
    view = df[cols].copy()

    # ---------- Стилизация ----------
    def style_row(row):
        styles = [""] * len(row)
        if "P/L ₽" in cols:
            i = cols.index("P/L ₽")
            v = row["P/L ₽"]
            if v > 0:
                styles[i] = "background-color: #C8E6C9; color: #1B5E20;"
            elif v < 0:
                styles[i] = "background-color: #FFCDD2; color: #B71C1C;"
        if "P/L %" in cols:
            i = cols.index("P/L %")
            v = row["P/L %"]
            if v > 0:
                styles[i] = "color: #1B5E20; font-weight: 600;"
            elif v < 0:
                styles[i] = "color: #B71C1C; font-weight: 600;"
        if "Рек. макс. цена" in cols and row["Рек. макс. цена"] > 0:
            i = cols.index("Рек. макс. цена")
            if row["Цена"] < row["Рек. макс. цена"]:
                styles[i] = "background-color: #C8E6C9; color: #1B5E20;"
            else:
                styles[i] = "background-color: #FFCDD2; color: #B71C1C;"
        return styles

    fmt_all = {
        "№":                   "{:.0f}",
        "Лотов":               "{:.0f}",
        "Акций":               "{:.0f}",
        "ТВХ":                 "{:,.2f} ₽",
        "Цена":                "{:,.2f} ₽",
        "Стоимость":           "{:,.2f} ₽",
        "Рынок":               "{:,.2f} ₽",
        "P/L ₽":               "{:+,.2f} ₽",
        "P/L %":               "{:+.2f}%",
        "Доля %":              "{:.2f}%",
        "Див/акц":             "{:,.2f} ₽",
        "Див 12м":             "{:,.2f} ₽",
        "Див нетто":           "{:,.2f} ₽",
        "Див.дох. к ТВХ %":    "{:.2f}%",
        "Див.дох. к рынку %":  "{:.2f}%",
        "Рек. макс. цена":     "{:,.2f} ₽",
        "Листинг":             "{:.0f}",
    }
    fmt = {k: v for k, v in fmt_all.items() if k in view.columns}

    styled = view.style.apply(style_row, axis=1).format(fmt)
    st.dataframe(styled, use_container_width=True, hide_index=True, height=640)

    # ---------- Экспорт ----------
    csv_buf = io.StringIO()
    df[cols].to_csv(csv_buf, index=False, sep=";", decimal=",")
    st.download_button(
        "📥 Скачать CSV",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name=f"{name}.csv",
        mime="text/csv",
    )

    with st.expander("ℹ️ Как считаются метрики"):
        st.markdown(
            "- **Стоимость** = ТВХ × Лотов × Размер лота\n"
            "- **Рынок** = Цена (ISS) × Лотов × Размер лота\n"
            "- **P/L ₽** = Рынок − Стоимость\n"
            "- **P/L %** = (Цена / ТВХ − 1) × 100\n"
            "- **Доля %** = Рынок / Σ Рынок × 100\n"
            "- **Див 12м** = Дивиденд на акцию × Акций (прогноз с dohod.ru)\n"
            "- **Див нетто** = Див 12м × (1 − ставка налога)\n"
            "- **Рек. макс. цена** = Див 12м на акцию / (Ставка ЦБ / 100) — "
            "цена, при которой дивидендная доходность равна ключевой ставке\n\n"
            "Зелёная подсветка «Рек. макс. цена» — текущая цена ниже рекомендации "
            "(бумага недооценена по дивидендам); красная — выше."
        )
