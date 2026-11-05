from __future__ import annotations
import pandas as pd
from core.market import fetch_many_extreme_closes, fetch_many_dividends
from core import state
from core.config import DEFAULT_W_FORMATIONS

IMOEX_CONSTITUENTS = {
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "GMKN", "PLZL",
    "YDEX", "OZON", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "MTSS",
    "MGNT", "MOEX", "PHOR", "SNGS", "TATNP", "TRNFP", "AFKS", "RTKM",
    "SBERP", "BSPB", "SNGSP",
}


def _dsi_to_score(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(x):
        return 0.0
    if x <= 1.5:
        x = x * 100
    return float(min(max(x, 0.0), 100.0))


def get_div_yield_color(div_yield: float, cb_rate: float, index_div_yield: float) -> str:
    """Возвращает цвет для дивидендной доходности.
    Зелёный: > ставки ЦБ
    Синий: > доходности индекса стабильных дивидендов
    Красный: ниже обоих порогов"""
    if div_yield > cb_rate:
        return "green"
    elif div_yield > index_div_yield:
        return "blue"
    else:
        return "red"


def calc_ranking(
    df: pd.DataFrame,
    state_w_forms: dict,
    cb_rate: float,
    extreme_date: str,
    imoex_ext: float,
    imoex_curr: float,
    portfolio_data: list = None,
) -> pd.DataFrame:
    df = df.copy()

    # Создаём словарь ТВХ по портфелю
    tvh_map = {}
    if portfolio_data:
        for p in portfolio_data:
            ticker = p.get("Тикер")
            tvh = p.get("ТВХ")
            if ticker and tvh:
                try:
                    tvh_map[ticker] = float(tvh)
                except (TypeError, ValueError):
                    pass

    # Получаем корректировки из файла Отладка
    overrides = state.g("ticker_overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}

    # Получаем доходность индекса "Компании стабильных дивидендов"
    index_div_yield = float(state.g("index_div_yield", 0.0))

    # 1. W-формация
    w_forms = state_w_forms if state_w_forms else DEFAULT_W_FORMATIONS
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    df["w_form"] = df["SECID"].map(w_forms).fillna("-").astype(str).str.lower().str.strip()
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)

    # 2. Арсагера и DSI с приоритетом: Отладка > Источники > default
    fund_data = state.g("fundamental_data", {})
    if not isinstance(fund_data, dict):
        fund_data = {}

    def get_ars_score(ticker):
        # Приоритет: Отладка > Источники > default
        if ticker in overrides and overrides[ticker].get("ars_group"):
            group = overrides[ticker]["ars_group"]
        elif ticker in fund_data and fund_data[ticker].get("ars_group"):
            group = fund_data[ticker]["ars_group"]
        else:
            group = 0
        return {1: 100, 2: 75, 3: 50, 4: 25}.get(group, 0)

    def get_dsi_val(ticker):
        # Приоритет: Отладка > Источники > default
        if ticker in overrides and overrides[ticker].get("dsi"):
            return overrides[ticker]["dsi"]
        elif ticker in fund_data and fund_data[ticker].get("dsi"):
            return fund_data[ticker]["dsi"]
        return 0.0

    df["ars_group"] = df["SECID"].apply(lambda t:
        overrides.get(t, {}).get("ars_group", 0)
        if t in overrides and overrides[t].get("ars_group")
        else fund_data.get(t, {}).get("ars_group", 0)
        if t in fund_data
        else 0
    )
    df["score_arsagera"] = df["SECID"].apply(get_ars_score)
    df["dsi"] = df["SECID"].apply(get_dsi_val)
    df["score_dsi"] = df["dsi"].apply(_dsi_to_score)

    # 3. Параллельная загрузка
    tickers = df["SECID"].tolist()
    closes_on_extreme = fetch_many_extreme_closes(tickers, extreme_date)
    divs_data = fetch_many_dividends(tickers)

    # 4. Сила актива
    imoex_chg = (imoex_curr / imoex_ext - 1) if imoex_ext > 0 else 0.0

    def get_rel_strength(row):
        ticker = row["SECID"]
        price_curr = row["PRICE"]
        price_ext = closes_on_extreme.get(ticker, 0.0)
        if price_curr > 0 and price_ext > 0:
            stock_chg = (price_curr / price_ext - 1)
            val = (stock_chg - imoex_chg) * 100
            if pd.isna(val):
                return 0.0
            return val
        return 0.0

    df["rel_strength"] = df.apply(get_rel_strength, axis=1)
    df["score_strength"] = (df["rel_strength"] > 0).astype(int) * 100

    # 5. Дивиденды с приоритетом: Отладка > Источники > dohod.ru
    future_divs = state.g("future_dividends", {})
    if not isinstance(future_divs, dict):
        future_divs = {}

    def get_div_12m(ticker):
        # Приоритет: Отладка > Источники (future_dividends) > dohod.ru
        if ticker in overrides and overrides[ticker].get("div_12m"):
            return overrides[ticker]["div_12m"]
        elif ticker in future_divs:
            return future_divs[ticker]
        else:
            return divs_data.get(ticker, {}).get("div_12m", 0.0)

    df["div_12m"] = df["SECID"].apply(get_div_12m)

    # Дивидендная доходность по рынку
    df["div_yield"] = df.apply(
        lambda r: (r["div_12m"] / r["PRICE"] * 100) if r["PRICE"] > 0 else 0.0, axis=1
    )

    # Дивидендная доходность по ТВХ (для акций портфеля)
    df["div_yield_tvh"] = df["SECID"].apply(
        lambda t: (df.loc[df["SECID"] == t, "div_12m"].values[0] / tvh_map[t] * 100)
        if t in tvh_map and tvh_map[t] > 0
        else 0.0
    )

    # Балл дивидендной доходности
    def get_score_div(row):
        ticker = row["SECID"]
        market_yield = row["div_yield"]
        tvh_yield = row["div_yield_tvh"]
        if ticker in tvh_map and tvh_yield > 0:
            effective_yield = tvh_yield
        else:
            effective_yield = market_yield
        if effective_yield > cb_rate:
            return 100
        elif effective_yield > 0:
            return 50
        return 0

    df["score_div"] = df.apply(get_score_div, axis=1)

    # Цветовая индикация дивидендной доходности
    df["div_color"] = df.apply(
        lambda r: get_div_yield_color(r["div_yield"], cb_rate, index_div_yield), axis=1
    )
    df["div_color_tvh"] = df.apply(
        lambda r: get_div_yield_color(r["div_yield_tvh"], cb_rate, index_div_yield)
        if r["SECID"] in tvh_map and r["div_yield_tvh"] > 0
        else get_div_yield_color(r["div_yield"], cb_rate, index_div_yield), axis=1
    )

    # 6. Выплаты
    df["score_paid_12m"] = (df["div_12m"] > 0).astype(int) * 100

    # 7. Листинг
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)

    # 8. Индекс
    df["in_index"] = df["SECID"].isin(IMOEX_CONSTITUENTS)
    df["score_in_index"] = df["in_index"].astype(int) * 100

    # 9. Рекомендуемая цена
    df["recommended_price"] = df.apply(
        lambda r: round(r["div_12m"] / (cb_rate / 100), 2)
        if r["div_12m"] > 0 and cb_rate > 0
        else 0.0,
        axis=1,
    )

    score_cols = [
        "score_w", "score_arsagera", "score_strength",
        "score_div", "score_paid_12m", "score_dsi",
        "score_list", "score_in_index",
    ]
    df["total_score"] = df[df.columns.intersection(score_cols)].sum(axis=1)
    return df


def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0:
        return "green"
    if div_yield > cb_rate and rel_strength <= 0:
        return "yellow"
    if div_yield == 0 and rel_strength > 0:
        return "orange"
    return "red"
