import pandas as pd
from core.market import fetch_extreme_close, fetch_dividends_dohod
from core import state

IMOEX_CONSTITUENTS = {
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "GMKN", "PLZL", 
    "YNDX", "OZON", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "MTSS", 
    "MGNT", "MOEX", "PHOR", "SNGS", "TATNP", "TRNFP", "AFKS", "RTKM"
}

def calc_ranking(df: pd.DataFrame, state_w_forms: dict, cb_rate: float, closes_on_extreme: dict, imoex_ext: float, imoex_curr: float) -> pd.DataFrame:
    df = df.copy()
    
    # 1. W-формация (до 100)
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    df["w_form"] = df["SECID"].map(state_w_forms).fillna("-")
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)
    
    # 2. Рейтинг Арсагера (до 100)
    arsagera_groups = state.g("arsagera_groups", {})
    ars_scores = {1: 100, 2: 75, 3: 50, 4: 25}
    df["ars_group"] = df["SECID"].map(arsagera_groups).fillna(0).astype(int)
    df["score_arsagera"] = df["ars_group"].map(ars_scores).fillna(0)
    
    # 3. Выше/ниже индекса (до 100)
    imoex_chg = (imoex_curr / imoex_ext - 1) if imoex_ext > 0 else 0.0
    
    def get_rel_strength(row):
        ticker = row["SECID"]
        price_curr = row["PRICE"]
        price_ext = closes_on_extreme.get(ticker, 0.0)
        
        if price_curr > 0 and price_ext > 0:
            stock_chg = (price_curr / price_ext - 1)
            return (stock_chg - imoex_chg) * 100
        return 0.0
        
    df["rel_strength"] = df.apply(get_rel_strength, axis=1)
    df["score_strength"] = (df["rel_strength"] > 0).astype(int) * 100
    
    # 4. Дивиденды по рынку (до 100)
    def get_div_data(ticker):
        res = fetch_dividends_dohod(ticker)
        return res.get("div_12m", 0.0), res.get("dsi", 0.0)

    div_data = df["SECID"].apply(get_div_data)
    df["div_12m"] = [x[0] for x in div_data]
    df["dsi"] = [x[1] for x in div_data]
    
    df["div_yield"] = df.apply(lambda r: (r["div_12m"] / r["PRICE"] * 100) if r["PRICE"] > 0 else 0.0, axis=1)
    df["score_div"] = df.apply(lambda r: 100 if r["div_yield"] > cb_rate else (50 if r["div_yield"] > 0 else 0), axis=1)
    
    # 5. Выплачено за 12 месяцев (до 100)
    df["score_paid_12m"] = (df["div_12m"] > 0).astype(int) * 100
    
    # 6. DSI (до 100)
    df["score_dsi"] = df["dsi"] * 100
    
    # 7. Тип листинга (до 100)
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)
    
    # 8. В составе индекса (до 100)
    df["in_index"] = df["SECID"].isin(IMOEX_CONSTITUENTS)
    df["score_in_index"] = df["in_index"].astype(int) * 100
    
    # 9. Рекомендуемая цена
    df["recommended_price"] = df.apply(
        lambda r: round(r["div_12m"] / (cb_rate / 100), 2) if r["div_12m"] > 0 and cb_rate > 0 else 0.0, 
        axis=1
    )

    # Итоговая сумма баллов (8 компонентов, максимум 800)
    score_cols = [
        "score_w", 
        "score_arsagera",
        "score_strength", 
        "score_div", 
        "score_paid_12m", 
        "score_dsi", 
        "score_list",
        "score_in_index"
    ]
    df["total_score"] = df[score_cols].sum(axis=1)
    return df

def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0: return "green"
    if div_yield > cb_rate and rel_strength <= 0: return "yellow"
    if div_yield == 0 and rel_strength > 0: return "orange"
    return "red"
