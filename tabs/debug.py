from __future__ import annotations
import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks


def render_debug():
    st.subheader("Отладка и корректировка параметров")
    st.markdown("""
    Здесь можно вручную скорректировать **отдельные параметры** для акций.
    Изменится только тот параметр, который вы заполните — остальные останутся нетронутыми.
    
    **Приоритет данных:**
    1. Файл "Отладка" (Excel) — высший приоритет
    2. Файл "Источники" (Excel)
    3. Данные с dohod.ru / значения по умолчанию
    """)

    df_stocks = fetch_moex_stocks()
    if df_stocks.empty:
        st.warning("Нет данных MOEX.")
        return

    if "ticker_overrides" not in state.get_state()["global"]:
        state.set_global("ticker_overrides", {})

    overrides = state.g("ticker_overrides", {})
    cb_rate = float(state.g("cb_rate", 14.0))
    index_div_yield = float(state.g("index_div_yield", 0.0))

    st.markdown("### Корректировки параметров акций")

    override_tickers = list(overrides.keys())

    if not override_tickers:
        st.info("Нет активных корректировок. Загрузите файл 'Отладка.xlsx' в боковом меню или добавьте корректировку ниже.")

    if override_tickers:
        st.markdown("#### Активные корректировки")
        for ticker in sorted(override_tickers):
            data = overrides[ticker]
            div_val = data.get("div_12m")
            dsi_val = data.get("dsi")
            ars_val = data.get("ars_group")
            with st.container():
                st.markdown(f"**{ticker}**")
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                with c1: st.caption(f"Див. 12м: **{div_val if div_val else '—'}**")
                with c2: st.caption(f"DSI: **{dsi_val if dsi_val else '—'}**")
                with c3: st.caption(f"Арсагера: **{ars_val if ars_val else '—'}**")
                with c4:
                    if st.button("🗑 Удалить", key=f"del_override_{ticker}"):
                        del overrides[ticker]
                        state.set_global("ticker_overrides", overrides)
                        state.autosave(force=True)
                        st.rerun()
                st.divider()

    st.markdown("#### Добавить корректировку")
    st.caption("Заполните только те поля, которые нужно изменить. Пустые поля не будут применены.")

    all_tickers = sorted(df_stocks["SECID"].unique().tolist())
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

    with col1:
        selected_ticker = st.selectbox("Тикер", options=all_tickers, key="debug_ticker_select")
    with col2:
        fund_data = state.g("fundamental_data", {})
        current_dsi = fund_data.get(selected_ticker, {}).get("dsi", 0.0) if selected_ticker else 0.0
        dsi = st.number_input("DSI (0 = не менять)", value=0.0, step=0.01, min_value=0.0, max_value=1.0, format="%.2f", key="debug_dsi", help=f"Текущее из источников: {current_dsi:.2f}")
    with col3:
        current_ars = fund_data.get(selected_ticker, {}).get("ars_group", 0) if selected_ticker else 0
        ars_group = st.selectbox("Арсагера (0 = не менять)", options=[0, 1, 2, 3, 4], index=0, key="debug_ars_group", help=f"Текущая из источников: {current_ars}")
    with col4:
        current_div = state.g("future_dividends", {}).get(selected_ticker, 0.0) if selected_ticker else 0.0
        div_12m = st.number_input("Див. 12м (0 = не менять)", value=0.0, step=1.0, min_value=0.0, format="%.2f", key="debug_div_12m", help=f"Текущий из источников: {current_div:.2f}")
    with col5:
        st.write("")
        st.write("")
        add_clicked = st.button("💾 Сохранить", key="debug_add_override", use_container_width=True)

    if add_clicked and selected_ticker:
        override_entry = {}
        if dsi > 0: override_entry["dsi"] = dsi
        if ars_group > 0: override_entry["ars_group"] = ars_group
        if div_12m > 0: override_entry["div_12m"] = div_12m
        if override_entry:
            overrides[selected_ticker] = override_entry
            state.set_global("ticker_overrides", overrides)
            state.autosave(force=True)
            st.success(f"Корректировка для {selected_ticker} сохранена!")
            st.rerun()
        else:
            st.warning("Заполните хотя бы одно поле для корректировки.")

    st.divider()
    st.markdown("### Справка о приоритетах данных")
    st.markdown(f"""
    **Дивиденды (div_12m):**
    1. Файл "Отладка" (Excel) — высший приоритет
    2. Файл "Источники" (Excel)
    3. Данные с dohod.ru

    **DSI и Арсагера:**
    1. Файл "Отладка" (Excel) — высший приоритет
    2. Файл "Источники" (Excel)
    3. Значение по умолчанию (0)

    **Цветовая индикация дивидендной доходности:**
    - 🟢 Зелёный: доходность > ставки ЦБ ({cb_rate:.2f}%)
    - 🔵 Синий: доходность > индекса стаб.див ({index_div_yield*100:.2f}%)
    - 🔴 Красный: доходность ниже обоих порогов
    """)

    if overrides:
        st.divider()
        if st.button("🗑 Очистить все корректировки", key="debug_clear_all", use_container_width=True):
            state.set_global("ticker_overrides", {})
            state.autosave(force=True)
            st.success("Все корректировки удалены!")
            st.rerun()
