"""
Калькулятор акций MOEX — точка входа Streamlit.
Сайдбар: настройки + загрузка Источники.xlsx / Портфель.xlsx + импорт/экспорт JSON.
Вкладки: Обзор, Рейтинг, Индексы, Портфель, Калькулятор, Справка.
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------- Внутренние модули ----------
from core import config as cfg
from core.parsers import load_sources
from core.ranking import score_stock
from core.storage import save_profile, load_profile  # если функции называются иначе — поправьте импорт

from tabs import (
    main_table,
    rating,
    indices,
    portfolio,
    trade_planner,
    help as help_tab,
)

# ---------- Опционально: тема ----------
try:
    from ui.theme import inject_css
except Exception:  # темы может не быть
    def inject_css(*_a, **_kw):
        pass


# ============================================================
# Настройки страницы
# ============================================================
st.set_page_config(
    page_title="Калькулятор акций MOEX",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()


# ============================================================
# Дефолтные настройки (подтягиваем из core/config.py, если есть)
# ============================================================
DEFAULTS = {
    "cb_rate": getattr(cfg, "CB_RATE", 16.0),
    "deposit": getattr(cfg, "DEPOSIT", 1_000_000.0),
    "cash_reserve_pct": getattr(cfg, "CASH_RESERVE_PCT", 10.0),
    "extremum_date": getattr(cfg, "EXTREMUM_DATE", "2024-05-20"),
    "risk_per_trade_pct": getattr(cfg, "RISK_PER_TRADE_PCT", 2.0),
}


def _init_state() -> None:
    st.session_state.setdefault("cfg", dict(DEFAULTS))
    st.session_state.setdefault("sources", None)
    st.session_state.setdefault("portfolio", None)
    st.session_state.setdefault("portfolio_path", None)


_init_state()


# ============================================================
# Сайдбар — настройки
# ============================================================
with st.sidebar:
    st.title("⚙️ Настройки")

    c = st.session_state["cfg"]

    c["cb_rate"] = st.number_input(
        "Ставка ЦБ, %", min_value=0.0, max_value=100.0,
        value=float(c["cb_rate"]), step=0.25,
    )
    c["deposit"] = st.number_input(
        "Депозит, ₽", min_value=0.0,
        value=float(c["deposit"]), step=10_000.0, format="%.0f",
    )
    c["cash_reserve_pct"] = st.slider(
        "Резерв кэша, %", 0, 100,
        int(c["cash_reserve_pct"]),
    )
    c["risk_per_trade_pct"] = st.slider(
        "Риск на сделку, %", 0.1, 10.0,
        float(c["risk_per_trade_pct"]), step=0.1,
    )
    c["extremum_date"] = st.text_input(
        "Дата экстремума (YYYY-MM-DD)", value=c["extremum_date"],
    )

    st.divider()

    # ---------- Загрузка Источники.xlsx ----------
    st.subheader("📥 Источники.xlsx")
    uploaded_sources = st.file_uploader(
        "Арсагера + DSI + W-формации",
        type=["xlsx"], key="uploader_sources",
        help="Один файл, до трёх листов: 'Рейтинг арсагера', 'ДОХОД DSI', 'W-формации'",
    )
    if uploaded_sources is not None:
        # pandas не любит BytesIO при sheet_name + header=None в некоторых версиях — пишем во временный файл
        tmp = Path(tempfile.gettempdir()) / "Источники.xlsx"
        tmp.write_bytes(uploaded_sources.getbuffer())
        try:
            sources = load_sources(str(tmp))
            st.session_state["sources"] = sources
            st.success(
                f"Загружено: Арсагера {len(sources['arsagera'])}, "
                f"DSI {len(sources['dsi'])}, W {len(sources['w'])}"
            )
            if not sources["w"]:
                st.warning("Лист «W-формации» не найден или пуст — W-баллы будут 0.")
        except Exception as e:
            st.error(f"Ошибка парсинга: {e}")

    if st.session_state["sources"] is not None:
        src = st.session_state["sources"]
        with st.expander("Проверка парсинга", expanded=False):
            for tk in ("LKOH", "SBER", "TATN", "GAZP"):
                a = src["arsagera"].get(tk, {})
                d = src["dsi"].get(tk)
                w = src["w"].get(tk)
                st.caption(
                    f"{tk}: Арсагера={a.get('score', '—')} "
                    f"({a.get('name', '—')}), DSI={d if d is not None else '—'}, W={w or '—'}"
                )

    st.divider()

    # ---------- Загрузка Портфель.xlsx ----------
    st.subheader("📥 Портфель.xlsx")
    uploaded_portfolio = st.file_uploader(
        "Текущие позиции", type=["xlsx"], key="uploader_portfolio",
    )
    if uploaded_portfolio is not None:
        tmp_p = Path(tempfile.gettempdir()) / "Портфель.xlsx"
        tmp_p.write_bytes(uploaded_portfolio.getbuffer())
        try:
            df = pd.read_excel(str(tmp_p))
            st.session_state["portfolio"] = df
            st.session_state["portfolio_path"] = str(tmp_p)
            st.success(f"Портфель: {len(df)} позиций")
        except Exception as e:
            st.error(f"Ошибка чтения портфеля: {e}")

    st.divider()

    # ---------- JSON ----------
    st.subheader("💾 Профиль (JSON)")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📤 Экспорт", use_container_width=True):
            try:
                payload = {
                    "cfg": st.session_state["cfg"],
                    "portfolio": (
                        st.session_state["portfolio"].to_dict(orient="records")
                        if st.session_state.get("portfolio") is not None else []
                    ),
                }
                st.download_button(
                    "Скачать JSON",
                    data=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                    file_name="profile.json",
                    mime="application/json",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Экспорт: {e}")
    with col_b:
        uploaded_json = st.file_uploader("JSON", type=["json"], key="uploader_json", label_visibility="collapsed")
        if uploaded_json is not None:
            try:
                payload = json.loads(uploaded_json.getvalue().decode("utf-8"))
                if "cfg" in payload:
                    st.session_state["cfg"].update(payload["cfg"])
                if payload.get("portfolio"):
                    st.session_state["portfolio"] = pd.DataFrame(payload["portfolio"])
                st.success("Профиль загружен.")
            except Exception as e:
                st.error(f"Импорт: {e}")


# ============================================================
# Безопасный вызов render() у вкладки
# ============================================================
def _render_tab(mod, **ctx):
    """
    Вызывает mod.render(**ctx), передавая только те kwargs,
    которые реально есть в сигнатуре render(). Позволяет
    вкладкам иметь разные сигнатуры без падений.
    """
    fn = getattr(mod, "render", None)
    if fn is None:
        st.warning(f"В модуле {mod.__name__} нет функции render().")
        return
    params = inspect.signature(fn).parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_kwargs:
        fn(**ctx)
    else:
        fn(**{k: v for k, v in ctx.items() if k in params})


# ============================================================
# Основные вкладки
# ============================================================
sources = st.session_state.get("sources")
portfolio_df = st.session_state.get("portfolio")
app_cfg = st.session_state["cfg"]

# Предрасчёт рейтинга (если есть sources)
rating_rows = []
if sources:
    try:
        # market-данные вкладки rating.py получат сами; здесь только «сырые» sources,
        # чтобы вкладка могла отрисовать таблицу даже без рейтинга.
        rating_rows = [
            {"ticker": tk, **info, "dsi": sources["dsi"].get(tk),
             "w": sources["w"].get(tk)}
            for tk, info in sources["arsagera"].items()
        ]
    except Exception as e:
        st.error(f"Ошибка подготовки rating_rows: {e}")

tab_overview, tab_rating, tab_indices, tab_portfolio, tab_calc, tab_help = st.tabs(
    ["📊 Обзор", "🏆 Рейтинг", "🌐 Индексы", "💼 Портфель", "🧮 Калькулятор", "❓ Справка"]
)

with tab_overview:
    _render_tab(
        main_table,
        sources=sources,
        portfolio=portfolio_df,
        cfg=app_cfg,
        rating_rows=rating_rows,
    )

with tab_rating:
    _render_tab(
        rating,
        sources=sources,
        portfolio=portfolio_df,
        cfg=app_cfg,
        rating_rows=rating_rows,
        score_stock=score_stock,
    )

with tab_indices:
    _render_tab(
        indices,
        sources=sources,
        cfg=app_cfg,
    )

with tab_portfolio:
    _render_tab(
        portfolio,
        portfolio=portfolio_df,
        portfolio_path=st.session_state.get("portfolio_path"),
        sources=sources,
        cfg=app_cfg,
    )

with tab_calc:
    _render_tab(
        trade_planner,
        sources=sources,
        portfolio=portfolio_df,
        cfg=app_cfg,
    )

with tab_help:
    _render_tab(help_tab)
