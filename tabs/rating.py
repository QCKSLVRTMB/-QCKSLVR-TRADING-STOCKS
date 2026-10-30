import streamlit as st
import pandas as pd
from core.market import fetch_moex_stocks, fetch_moex_indices, fetch_extreme_close
from core.ranking import calc_ranking, get_asset_color
from core import state


def render_rating():
    st.subheader("Рейтинг акций")
    df_stocks = fetch_moex_stocks()
    df_indices = fetch_moex_indices()

    if df_stocks.empty or df_indices.empty:
        st.warning("Нет данных MOEX.")
        return

    # Оставляем все бумаги с ценой (исключаем только делистинг/без котировок).
    # VALTODAY > 0 НЕ используем — иначе выпадают низколиквидные бумаги.
    df_stocks = df_stocks[df_stocks["PRICE"] > 0].copy()

    extreme_date = state.g("extreme_date")

    with st.spinner(
        f"Расчёт рейтинга для {len(df_stocks)} бумаг "
        f"(первый запуск может занять 10–20 сек, далее — из кэша)..."
    ):
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID'] == 'IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0.0

        w_forms = state.g("w_formations")
        cb_rate = state.g("cb_rate")

        df_all = calc_ranking(df_stocks, w_forms, cb_rate, extreme_date, imoex_ext, imoex_curr)

    # ============================================================
    # ФИЛЬТРЫ
    # ============================================================
    st.markdown("#### Фильтры")

    fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
    with fc1:
        search = st.text_input(
            "Поиск", placeholder="Тикер или название (LKOH, Сбер, ...)",
            key="rating_search", label_visibility="collapsed",
        )
    with fc2:
        min_score = st.number_input(
            "Мин. балл", min_value=0, max_value=800, value=0, step=50,
            key="rating_min_score",
        )
    with fc3:
        w_filter = st.selectbox(
            "W-формация",
            ["все", "только с данными", "вверх", "рейндж", "вниз", "нет данных"],
            key="rating_w",
        )
    with fc4:
        ars_filter = st.selectbox(
            "Арсагера",
            ["все", "Группа 1", "Группа 2", "Группа 3", "Группа 4", "Нет данных"],
            key="rating_ars",
        )

    fc5, fc6, fc7, fc8 = st.columns(4)
    with fc5:
        imoex_filter = st.selectbox("IMOEX", ["все", "да", "нет"], key="rating_imoex")
    with fc6:
        list_filter = st.selectbox("Листинг", ["все", 1, 2, 3], key="rating_list")
    with fc7:
        min_vol = st.number_input(
            "Мин. объём, ₽", min_value=0, value=0, step=100_000,
            key="rating_min_vol",
        )
    with fc8:
        sort_by = st.selectbox(
            "Сортировка",
            ["Баллы ↓", "Баллы ↑", "Тикер", "Сила актива ↓", "Див. доходность ↓"],
            key="rating_sort",
        )

    # --- Применение фильтров ---
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

    # --- Сортировка ---
    sort_map = {
        "Баллы ↓":           ("total_score",   False),
        "Баллы ↑":           ("total_score",   True),
        "Тикер":             ("SECID",         True),
        "Сила актива ↓":     ("rel_strength",  False),
        "Див. доходность ↓": ("div_yield",     False),
    }
    col, asc = sort_map[sort_by]
    df = df.sort_values(col, ascending=asc).reset_index(drop=True)

    st.caption(
        f"Показано **{len(df)}** из **{len(df_all)}** бумаг "
        f"(всего в ISS TQBR: {len(df_stocks)})"
    )

    if df.empty:
        st.info("Нет бумаг, удовлетворяющих фильтрам.")
        if st.button("🗑 Сбросить фильтры"):
            _reset_filters()
        return

    # ============================================================
    # ТАБЛИЦА
    # ============================================================
    df["№"] = df.index + 1
    df["in_index_str"] = df["in_index"].map({True: "да", False: "нет"})

    display_df = pd.DataFrame({
        "№": df["№"],
        "Название": df["SHORTNAME"],
        "Тикер": df["SECID"],
        "Вид актива": df.apply(
            lambda r: get_asset_color(r["div_yield"], cb_rate, r["rel_strength"]),
            axis=1,
        ),
        "W-формация": df["w_form"],
        "Арсагера": df["ars_group"],
        "В составе индекса": df["in_index_str"],
        "Сила актива": df["rel_strength"],
        "Дивидендная доходность (по рынку)": df["div_yield"],
        "DSI": df["dsi"],
        "Тип листинга": df["LISTLEVEL"],
        "Сумма баллов": df["total_score"],
        "Рекомендуемая цена": df["recommended_price"],
    })

    def apply_styles(row):
        styles = [""] * len(row)

        w = row["W-формация"]
        if w == "вверх":   styles[4] = "background-color: #4CAF50; color: white;"
        elif w == "рейндж": styles[4] = "background-color: #2196F3; color: white;"
        elif w == "вниз":   styles[4] = "background-color: #F44336; color: white;"

        if row["В составе индекса"] == "да":
            styles[6] = "background-color: #4CAF50; color: white;"
        else:
            styles[6] = "background-color: #F44336; color: white;"

        if row["Сила актива"] > 0:
            styles[7] = "background-color: #4CAF50; color: white;"
        else:
            styles[7] = "background-color: #F44336; color: white;"

        color = row["Вид актива"]
        if color == "green":   styles[3] = "background-color: #4CAF50; color: #4CAF50;"
        elif color == "yellow": styles[3] = "background-color: #FFEB3B; color: #FFEB3B;"
        elif color == "orange": styles[3] = "background-color: #FF9800; color: #FF9800;"
        elif color == "red":    styles[3] = "background-color: #F44336; color: #F44336;"

        return styles

    styled_df = (
        display_df.style
        .apply(apply_styles, axis=1)
        .format({
            "Вид актива": lambda x: "",
            "Сила актива": "{:+.2f}%",
            "Дивидендная доходность (по рынку)": "{:.2f}%",
            "DSI": "{:.2f}",
            "Тип листинга": "{:.0f}",
            "Сумма баллов": "{:.0f}",
            "Рекомендуемая цена": "{:.2f} ₽",
            "№": "{:.0f}",
        })
    )

    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        height=800,
    )

    if st.button("🗑 Сбросить все фильтры"):
        _reset_filters()


def _reset_filters():
    for k in (
        "rating_search", "rating_min_score", "rating_w", "rating_ars",
        "rating_imoex", "rating_list", "rating_min_vol", "rating_sort",
    ):
        st.session_state.pop(k, None)
    st.rerun()
