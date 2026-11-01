from __future__ import annotations
import streamlit as st
import pandas as pd
from core import state
from core.market import fetch_moex_stocks


def render_debug():
    """Вкладка для ручной корректировки параметров акций в рейтинге."""
    st.subheader("Отладка и корректировка параметров")
    st.markdown("""
    Здесь можно вручную скорректировать параметры для отдельных акций.
    Эти корректировки сохранятся в JSON и будут применяться при расчете рейтинга.
    
    **Приоритет данных:**
    - Дивиденды и DSI из файла "Источники" (Excel) имеют приоритет над корректировками
    - Корректировки имеют приоритет над данными с dohod.ru
    - ТВХ и лоты приоритетнее из JSON (портфель)
    """)
    
    df_stocks = fetch_moex_stocks()
    if df_stocks.empty:
        st.warning("Нет данных MOEX.")
        return
    
    # Инициализация структуры корректировок
    if "ticker_overrides" not in state.get_state()["global"]:
        state.set_global("ticker_overrides", {})
    
    overrides = state.g("ticker_overrides", {})
    
    st.markdown("### Корректировки параметров акций")
    
    # Получаем список тикеров с корректировками
    override_tickers = list(overrides.keys())
    
    if not override_tickers:
        st.info("Нет активных корректировок. Добавьте новую корректировку ниже.")
    
    # Отображаем существующие корректировки
    if override_tickers:
        st.markdown("#### Активные корректировки")
        
        rows = []
        for ticker in override_tickers:
            data = overrides[ticker]
            rows.append({
                "Тикер": ticker,
                "Див. 12м (корр.)": data.get("div_12m", ""),
                "DSI (корр.)": data.get("dsi", ""),
                "Арсагера (корр.)": data.get("ars_group", ""),
            })
        
        df_overrides = pd.DataFrame(rows)
        
        # Кнопка удаления для каждой корректировки
        for idx, row in df_overrides.iterrows():
            col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 0.5])
            with col1:
                st.text(f"**{row['Тикер']}**")
            with col2:
                st.text(f"Див: {row['Див. 12м (корр.)']}" if row['Див. 12м (корр.)'] else "Див: —")
            with col3:
                st.text(f"DSI: {row['DSI (корр.)']}" if row['DSI (корр.)'] else "DSI: —")
            with col4:
                st.text(f"Арс: {row['Арсагера (корр.)']}" if row['Арсагера (корр.)'] else "Арс: —")
            with col5:
                if st.button("🗑", key=f"del_override_{row['Тикер']}"):
                    del overrides[row['Тикер']]
                    state.set_global("ticker_overrides", overrides)
                    state.autosave(force=True)
                    st.rerun()
        
        st.divider()
    
    # Форма добавления новой корректировки
    st.markdown("#### Добавить корректировку")
    
    all_tickers = sorted(df_stocks["SECID"].unique().tolist())
    
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        selected_ticker = st.selectbox(
            "Тикер",
            options=all_tickers,
            key="debug_ticker_select"
        )
    
    with col2:
        div_12m = st.number_input(
            "Див. 12м",
            value=0.0,
            step=0.01,
            format="%.2f",
            key="debug_div_12m"
        )
    
    with col3:
        dsi = st.number_input(
            "DSI",
            value=0.0,
            step=0.01,
            min_value=0.0,
            max_value=1.0,
            format="%.2f",
            key="debug_dsi"
        )
    
    with col4:
        ars_group = st.selectbox(
            "Арсагера",
            options=[0, 1, 2, 3, 4],
            index=0,
            key="debug_ars_group"
        )
    
    if st.button("Добавить/Обновить корректировку", key="debug_add_override", use_container_width=True):
        if selected_ticker:
            overrides[selected_ticker] = {
                "div_12m": div_12m if div_12m > 0 else None,
                "dsi": dsi if dsi > 0 else None,
                "ars_group": ars_group if ars_group > 0 else None
            }
            state.set_global("ticker_overrides", overrides)
            state.autosave(force=True)
            st.success(f"Корректировка для {selected_ticker} сохранена!")
            st.rerun()
    
    st.divider()
    
    # Информация о приоритетах
    st.markdown("### Справка о приоритетах данных")
    
    st.markdown("""
    **Дивиденды (div_12m):**
    1. Файл "Источники" (Excel) — высший приоритет
    2. Корректировка из этой вкладки
    3. Данные с dohod.ru
    
    **DSI:**
    1. Файл "Источники" (Excel) — высший приоритет
    2. Корректировка из этой вкладки
    3. Значение по умолчанию (0)
    
    **Группа Арсагера:**
    1. Файл "Источники" (Excel) — высший приоритет
    2. Корректировка из этой вкладки
    3. Значение по умолчанию (0)
    
    **ТВХ и лоты:**
    1. JSON (портфель) — высший приоритет
    2. Файл "Портфель" (Excel)
    """)
    
    # Кнопка очистки всех корректировок
    if overrides:
        st.divider()
        if st.button("🗑 Очистить все корректировки", key="debug_clear_all", use_container_width=True):
            state.set_global("ticker_overrides", {})
            state.autosave(force=True)
            st.success("Все корректировки удалены!")
            st.rerun()
