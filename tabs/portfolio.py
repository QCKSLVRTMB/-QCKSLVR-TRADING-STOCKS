import streamlit as st
import pandas as pd

from core import state
from core.market import fetch_moex_stocks, fetch_dividends_dohod
from core.calc import get_instrument


# ============================================================
# Утилиты
# ============================================================
def _detect_columns(df: pd.DataFrame) -> dict:
    """Находит в произвольном DataFrame колонки: тикер, средняя цена, количество."""
    if df is None or df.empty:
        return {"ticker": None, "price": None, "qty": None}

    norm = {c: str(c).strip().lower() for c in df.columns}

    def find(patterns):
        for c, name in norm.items():
            for p in patterns:
                if p in name:
                    return c
        return None

    return {
        "ticker": find(["тикер", "ticker", "secid", "symbol", "бумага", "актив"]),
        "price":  find(["средн", "твх", "avg", "average", "цена входа",
                        "цена покупки", "цена"]),
        "qty":    find(["колич", "лотов", "кол-во", "кол-во лотов", "qty",
                        "quantity", "lots", "шт"]),
    }


def _portfolio_total_value(port_df: pd.DataFrame, df_stocks: pd.DataFrame,
                           colmap: dict) -> float:
    """Сумма (средняя цена × лоты × размер лота) по всем позициям."""
    if port_df is None or port_df.empty:
        return 0.0
    t_c, p_c, q_c = colmap["ticker"], colmap["price"], colmap["qty"]
    if not (t_c and p_c and q_c):
        return 0.0
    total = 0.0
    for _, r in port_df.iterrows():
        t = str(r[t_c]).strip().upper()
        try:
            avg = float(r[p_c])
            lots = float(r[q_c])
        except (TypeError, ValueError):
            continue
        inst = get_instrument(t, df_stocks)
        lot_size = inst.lot_size or 1
        total += avg * lots * lot_size
    return total


def _fmt_money(v: float) -> str:
    return f"{v:,.0f} ₽".replace(",", " ")


def _fmt_price(v: float, decimals: int) -> str:
    return f"{v:,.{decimals}f} ₽".replace(",", " ")


# ============================================================
# Главный вход вкладки
# ============================================================
def render_portfolio(df_stocks: pd.DataFrame):
    st.subheader("Портфель")

    port_data = state.g("portfolio_data", [])
    if not port_data:
        st.info("Загрузите файл портфеля в боковом меню для отображения таблицы.")
        return

    df_port = pd.DataFrame(port_data)
    if df_port.empty:
        st.warning("Данные портфеля пусты.")
        return

    colmap = _detect_columns(df_port)

    # ---------- Таблица: показываем ВСЕ строки без скролла ----------
    st.markdown("#### Позиции")
    row_height = 35
    header_height = 40
    # Ограничиваем сверху на случай гигантского портфеля — но обычно 5..30 строк.
    table_height = header_height + row_height * len(df_port) + 6

    st.dataframe(
        df_port,
        use_container_width=True,
        hide_index=True,
        height=table_height,
    )

    st.caption(
        f"Позиций: **{len(df_port)}** · "
        f"Стоимость портфеля по средней цене: "
        f"**{_fmt_money(_portfolio_total_value(df_port, df_stocks, colmap))}**"
    )

    # ---------- Калькулятор ----------
    _render_averaging_calculator(df_port, df_stocks, colmap)


# ============================================================
# Калькулятор усреднения
# ============================================================
def _render_averaging_calculator(port_df: pd.DataFrame,
                                 df_stocks: pd.DataFrame,
                                 colmap: dict):
    st.markdown("---")
    st.markdown("### 🧮 Калькулятор усреднения позиции")

    t_c, p_c, q_c = colmap["ticker"], colmap["price"], colmap["qty"]
    if not (t_c and p_c and q_c):
        st.error(
            "Не удалось определить колонки портфеля. "
            "Нужны колонки: **Тикер**, **Средняя цена** (или Цена), **Количество лотов**."
        )
        st.caption(
            "Найденные колонки в файле: " + ", ".join(str(c) for c in port_df.columns)
        )
        return

    tickers = (
        port_df[t_c].dropna().astype(str).str.strip().str.upper().tolist()
    )
    tickers = [t for t in tickers if t]
    if not tickers:
        st.info("В портфеле нет тикеров.")
        return

    # ---------- Селектор актива ----------
    sel_ticker = st.selectbox(
        "Актив из портфеля",
        tickers,
        key="avg_ticker",
        help="Выберите позицию — ТВХ и количество лотов подставятся автоматически.",
    )

    row = port_df[
        port_df[t_c].astype(str).str.strip().str.upper() == sel_ticker
    ].iloc[0]

    try:
        old_avg = float(row[p_c])
    except (TypeError, ValueError):
        old_avg = 0.0
    try:
        old_lots = int(row[q_c])
    except (TypeError, ValueError):
        old_lots = 0

    inst = get_instrument(sel_ticker, df_stocks)
    current_price = inst.price or 0.0
    lot_size = inst.lot_size or 1
    decimals = inst.decimals or 2
    min_step = float(inst.min_step or (10 ** -decimals))
    t_name = inst.name or sel_ticker

    # Дивиденды на акцию (12м) — только для выбранного тикера (быстрый точечный запрос)
    with st.spinner(f"Загрузка дивидендов {sel_ticker}…"):
        divs = fetch_dividends_dohod(sel_ticker)
    div_12m = float(divs.get("div_12m") or 0.0)

    # DSI из Excel-источника
    fund = state.g("fundamental_data", {}) or {}
    dsi_raw = fund.get(sel_ticker, {}).get("dsi")
    dsi_score = None
    if dsi_raw is not None:
        try:
            v = float(dsi_raw)
            dsi_score = v * 100 if v <= 1.5 else v
        except (TypeError, ValueError):
            dsi_score = None

    # ---------- Текущее состояние (автоподстановка) ----------
    st.markdown(f"#### {sel_ticker} — {t_name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Текущее ТВХ", _fmt_price(old_avg, decimals) if old_avg else "—")
    c2.metric("Лотов в портфеле", str(old_lots))
    c3.metric("Текущая цена", _fmt_price(current_price, decimals) if current_price else "—")
    c4.metric(
        "Див. на акцию (12м)",
        _fmt_price(div_12m, decimals) if div_12m else "—",
    )

    # ---------- Докупка ----------
    st.markdown("#### Докупка")
    ic1, ic2 = st.columns(2)

    # Ключи зависят от тикера → каждое плечо помнит свои значения
    with ic1:
        new_price = st.number_input(
            "Цена покупки, ₽",
            min_value=0.0,
            value=float(current_price) if current_price > 0 else 0.0,
            step=min_step,
            format=f"%.{decimals}f",
            key=f"avg_new_price_{sel_ticker}",
        )
    with ic2:
        new_lots = st.number_input(
            "Лотов докупить",
            min_value=0,
            value=0,
            step=1,
            key=f"avg_new_lots_{sel_ticker}",
        )

    # ---------- Результат ----------
    if new_lots > 0 and new_price > 0:
        old_cost = old_avg * old_lots
        new_cost = new_price * new_lots
        total_lots = old_lots + new_lots
        new_avg = (old_cost + new_cost) / total_lots if total_lots > 0 else 0.0

        st.markdown("#### Результат усреднения")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric(
            "Новое ТВХ",
            _fmt_price(new_avg, decimals),
            f"{new_avg - old_avg:+.{decimals}f} ₽" if old_avg else None,
        )
        r2.metric("Всего лотов", str(total_lots), f"+{new_lots}")
        r3.metric(
            "Стоимость новой позиции",
            _fmt_money(new_avg * total_lots * lot_size),
        )
        r4.metric(
            "Затраты на докупку",
            _fmt_money(new_price * new_lots * lot_size),
        )

        st.markdown("#### Метрики позиции")
        m1, m2, m3, m4 = st.columns(4)

        # P/L и доходность при текущей рыночной цене
        if current_price > 0 and new_avg > 0:
            pl_rub = (current_price - new_avg) * total_lots * lot_size
            pl_pct = (current_price / new_avg - 1) * 100
            m1.metric(
                "P/L по новой позиции",
                _fmt_money(pl_rub),
                f"{pl_pct:+.2f}%",
            )
        else:
            m1.metric("P/L по новой позиции", "—")

        # Обновлённая дивидендная доходность
        if div_12m > 0 and new_avg > 0:
            yield_old = (div_12m / old_avg * 100) if old_avg > 0 else 0.0
            yield_new = div_12m / new_avg * 100
            delta = yield_new - yield_old if old_avg > 0 else None
            m2.metric(
                "Див. доходность (новая)",
                f"{yield_new:.2f}%",
                f"{delta:+.2f}%" if delta is not None else None,
            )
        else:
            m2.metric("Див. доходность (новая)", "—")

        # Годовой дивидендный поток
        annual_div = div_12m * total_lots * lot_size
        m3.metric(
            "Годовой дивидендный поток",
            _fmt_money(annual_div) if annual_div > 0 else "—",
        )

        # DSI
        m4.metric(
            "DSI",
            f"{dsi_score:.0f}" if dsi_score is not None else "—",
        )

        # Доп. контекст: вес в портфеле и старый P/L
        total_port_value = _portfolio_total_value(port_df, df_stocks, colmap)
        new_pos_value = new_avg * total_lots * lot_size

        if total_port_value > 0 and new_avg > 0:
            weight_old = (
                old_avg * old_lots * lot_size / total_port_value * 100
                if old_avg > 0 else 0.0
            )
            weight_new = new_pos_value / total_port_value * 100
            st.caption(
                f"Вес позиции в портфеле: было **{weight_old:.1f}%** → "
                f"станет **{weight_new:.1f}%** "
                f"(Δ {weight_new - weight_old:+.1f} п.п.)"
            )

        # Сравнение с текущей ценой
        if current_price > 0 and new_avg > 0:
            spread = (current_price - new_avg) / new_avg * 100
            if spread > 0:
                st.success(
                    f"Текущая цена выше нового ТВХ на **{spread:+.2f}%** — позиция в плюсе."
                )
            elif spread < 0:
                st.warning(
                    f"Текущая цена ниже нового ТВХ на **{spread:+.2f}%** — позиция в минусе."
                )
    else:
        st.caption(
            "Введите цену и количество лотов для докупки, "
            "чтобы увидеть результат усреднения."
        )
