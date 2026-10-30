"""
Калькулятор акций MOEX — точка входа Streamlit.
"""
from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from core import state as app_state

st.set_page_config(
    page_title="Калькулятор акций MOEX",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Безопасные импорты
# ============================================================
def _safe_import(module_path: str, names: list[str] | None = None, required: bool = False):
    try:
        mod = __import__(module_path, fromlist=names or ["*"])
        if names:
            missing = [n for n in names if not hasattr(mod, n)]
            if missing:
                msg = f"В модуле {module_path} нет: {', '.join(missing)}"
                (st.error if required else st.warning)(msg)
                if required:
                    st.stop()
                return None
        return mod
    except Exception as e:
        msg = f"Не удалось импортировать {module_path}: {e!r}"
        (st.error if required else st.warning)(msg)
        if required:
            st.stop()
        return None


cfg        = _safe_import("core.config", required=False)
parsers    = _safe_import("core.parsers", names=["load_sources"], required=False)
ranking    = _safe_import("core.ranking", names=["calc_ranking"], required=False)
storage    = _safe_import("core.storage", required=False)
theme      = _safe_import("ui.theme", required=False)

load_sources = getattr(parsers, "load_sources", None)
calc_ranking = getattr(ranking, "calc_ranking", None)

if load_sources is None:
    st.error("**core/parsers.py** не найден или не экспортирует `load_sources`.")
if calc_ranking is None:
    st.error("**core/ranking.py** не экспортирует `calc_ranking`.")

if theme and hasattr(theme, "inject_css"):
    try:
        theme.inject_css()
    except Exception as e:
        st.warning(f"ui.theme.inject_css упал: {e!r}")

tab_modules = {}
for name in ("main_table", "rating", "indices", "portfolio", "trade_planner", "help"):
    tab_modules[name] = _safe_import(f"tabs.{name}", required=False)


# ============================================================
# Дефолты
# ============================================================
DEFAULTS = {
    # cb_rate — в ПРОЦЕНТАХ, как ждёт core/ranking.py
    "cb_rate": float(getattr(cfg, "CB_RATE", 16.0)) if cfg else 16.0,
    "deposit": float(getattr(cfg, "DEPOSIT", 1_000_000.0)) if cfg else 1_000_000.0,
    "cash_reserve_pct": float(getattr(cfg, "CASH_RESERVE_PCT", 10.0)) if cfg else 10.0,
    "extremum_date": str(getattr(cfg, "EXTREMUM_DATE", "2024-05-20")) if cfg else "2024-05-20",
    "risk_per_trade_pct": float(getattr(cfg, "RISK_PER_TRADE_PCT", 2.0)) if cfg else 2.0,
}
st.session_state.setdefault("cfg", dict(DEFAULTS))
st.session_state.setdefault("sources", None)
st.session_state.setdefault("portfolio", None)
st.session_state.setdefault("portfolio_path", None)


def _push_sources_to_state(sources: dict) -> None:
    """
    Перекладывает результат load_sources() в формат, который читает calc_ranking:
      state.g('fundamental_data') = { ticker: {'ars_group': int, 'dsi': float(0..1)} }
      state.g('w_formations')     = { ticker: 'вверх'|'вниз'|'рейндж' }
    """
    if not sources:
        return
    fundamental = {}
    for tk, info in sources.get("arsagera", {}).items():
        dsi_raw = sources.get("dsi", {}).get(tk)
        # parsers возвращает DSI уже ×100 (96.0), приводим к 0..1 как ждёт calc_ranking
        dsi_val = (float(dsi_raw) / 100.0) if dsi_raw is not None else 0.0
        fundamental[tk] = {
            "ars_group": int(info.get("group", 0) or 0),
            "dsi": dsi_val,
        }
    app_state.s("fundamental_data", fundamental)
    app_state.s("w_formations", dict(sources.get("w") or {}))


# ============================================================
# Сайдбар
# ============================================================
with st.sidebar:
    st.title("⚙️ Настройки")
    c = st.session_state["cfg"]

    c["cb_rate"] = st.number_input(
        "Ставка ЦБ, %",                       # ← процент, как в calc_ranking
        min_value=0.0, max_value=100.0,
        value=float(c["cb_rate"]),
        step=0.25,
    )
    c["deposit"] = st.number_input(
        "Депозит, ₽", min_value=0.0,
        value=float(c["deposit"]), step=10_000.0, format="%.0f",
    )
    c["cash_reserve_pct"] = st.slider(
        "Резерв кэша, %", 0, 100, int(c["cash_reserve_pct"]),
    )
    c["risk_per_trade_pct"] = st.slider(
        "Риск на сделку, %", 0.1, 10.0, float(c["risk_per_trade_pct"]), step=0.1,
    )
    c["extremum_date"] = st.text_input(
        "Дата экстремума (YYYY-MM-DD)", value=c["extremum_date"],
    )

    st.divider()
    st.subheader("📥 Источники.xlsx")
    uploaded_sources = st.file_uploader(
        "Арсагера + DSI + W-формации",
        type=["xlsx"], key="uploader_sources",
    )
    if uploaded_sources is not None and load_sources is not None:
        tmp = Path(tempfile.gettempdir()) / "Источники.xlsx"
        tmp.write_bytes(uploaded_sources.getbuffer())
        try:
            sources = load_sources(str(tmp))
            st.session_state["sources"] = sources
            _push_sources_to_state(sources)          # ← ключевая связка
            st.success(
                f"Арсагера {len(sources['arsagera'])}, "
                f"DSI {len(sources['dsi'])}, W {len(sources['w'])}"
            )
            if not sources["w"]:
                st.warning("Лист «W-формации» пуст — W-баллы будут 0.")
        except Exception as e:
            st.error(f"Ошибка парсинга Источники.xlsx: {e!r}")

    src = st.session_state.get("sources")
    if src:
        with st.expander("Проверка парсинга", expanded=False):
            for tk in ("LKOH", "SBER", "TATN", "GAZP"):
                a = src["arsagera"].get(tk, {})
                d = src["dsi"].get(tk)
                w = src["w"].get(tk)
                st.caption(
                    f"**{tk}** — Арсагера={a.get('score', '—')} "
                    f"({a.get('name', '—')}), DSI={d if d is not None else '—'}, "
                    f"W={w or '—'}"
                )

    st.divider()
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
            st.error(f"Ошибка чтения Портфель.xlsx: {e!r}")

    st.divider()
    st.subheader("💾 Профиль (JSON)")
    if st.button("📤 Экспорт", use_container_width=True):
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
    uploaded_json = st.file_uploader(
        "JSON", type=["json"], key="uploader_json", label_visibility="collapsed",
    )
    if uploaded_json is not None:
        try:
            payload = json.loads(uploaded_json.getvalue().decode("utf-8"))
            st.session_state["cfg"].update(payload.get("cfg", {}))
            if payload.get("portfolio"):
                st.session_state["portfolio"] = pd.DataFrame(payload["portfolio"])
            st.success("Профиль загружен.")
        except Exception as e:
            st.error(f"Импорт JSON: {e!r}")


# ============================================================
# Безопасный вызов render()
# ============================================================
def _render_tab(mod, **ctx):
    if mod is None:
        st.info("Модуль вкладки недоступен — см. предупреждения выше.")
        return
    fn = getattr(mod, "render", None)
    if fn is None:
        st.warning(f"В модуле {mod.__name__} нет функции render().")
        return
    params = inspect.signature(fn).parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        fn(**ctx)
    else:
        fn(**{k: v for k, v in ctx.items() if k in params})


# ============================================================
# Вкладки
# ============================================================
sources = st.session_state.get("sources")
portfolio_df = st.session_state.get("portfolio")
app_cfg = st.session_state["cfg"]

t1, t2, t3, t4, t5, t6 = st.tabs(
    ["📊 Обзор", "🏆 Рейтинг", "🌐 Индексы", "💼 Портфель", "🧮 Калькулятор", "❓ Справка"]
)

with t1:
    _render_tab(tab_modules["main_table"],
                sources=sources, portfolio=portfolio_df, cfg=app_cfg)
with t2:
    _render_tab(tab_modules["rating"],
                sources=sources, portfolio=portfolio_df, cfg=app_cfg)
with t3:
    _render_tab(tab_modules["indices"], sources=sources, cfg=app_cfg)
with t4:
    _render_tab(tab_modules["portfolio"],
                portfolio=portfolio_df,
                portfolio_path=st.session_state.get("portfolio_path"),
                sources=sources, cfg=app_cfg)
with t5:
    _render_tab(tab_modules["trade_planner"],
                sources=sources, portfolio=portfolio_df, cfg=app_cfg)
with t6:
    _render_tab(tab_modules["help"])
