import pandas as pd
from core.market import fetch_extreme_close, fetch_dividends_dohod
from core import state
from core.config import DEFAULT_ARSAGERA_GROUPS, DEFAULT_W_FORMATIONS

IMOEX_CONSTITUENTS = {
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "GMKN", "PLZL", 
    "YNDX", "OZON", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "MTSS", 
    "MGNT", "MOEX", "PHOR", "SNGS", "TATNP", "TRNFP", "AFKS", "RTKM"
}

def calc_ranking(df: pd.DataFrame, state_w_forms: dict, cb_rate: float, closes_on_extreme: dict, imoex_ext: float, imoex_curr: float) -> pd.DataFrame:
    df = df.copy()
    
    # 1. W-формация
    w_forms = state_w_forms if state_w_forms else DEFAULT_W_FORMATIONS
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    df["w_form"] = df["SECID"].map(w_forms).fillna("-")
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)
    
    # 2. Арсагера и DSI
    fund_data = state.g("fundamental_data", {})
    
    def get_ars_score(ticker):
        # 1. Берем из Excel, если загружен
        if ticker in fund_data and fund_data[ticker].get("ars_group", 0) > 0:
            group = fund_data[ticker]["ars_group"]
            return {1: 100, 2: 75, 3: 50, 4: 25}.get(group, 0)
        # 2. Иначе берем дефолт из конфига (Лукойл = 1 группа = 100 баллов)
        group = DEFAULT_ARSAGERA_GROUPS.get(ticker, 0)
        return {1: 100, 2: 75, 3: 50, 4: 25}.get(group, 0)

    def get_div_data(ticker):
        res = fetch_dividends_dohod(ticker)
        div_12m = res.get("div_12m", 0.0)
        dsi_dohod = res.get("dsi", 0.0)
        
        # Если в Excel есть DSI, он перекрывает значение с dohod.ru
        if ticker in fund_data:
            dsi_fund = fund_data[ticker].get("dsi", 0.0)
            if dsi_fund > 0:
                dsi_dohod = dsi_fund
                
        return div_12m, dsi_dohod

    div_data = df["SECID"].apply(get_div_data)
    df["div_12m"] = [x[0] for x in div_data]
    df["dsi"] = [x[1] for x in div_data]
    
    df["score_arsagera"] = df["SECID"].apply(get_ars_score)
    df["score_dsi"] = df["dsi"].fillna(0).clip(upper=1.0) * 100
    
    # 3. Сила актива
    imoex_chg = (imoex_curr / imoex_ext - 1) if imoex_ext > 0 else 0.0
    
    def get_rel_strength(row):
        ticker = row["SECID"]
        price_curr = row["PRICE"]
        price_ext = closes_on_extreme.get(ticker, 0.0)
        
        if price_curr > 0 and price_ext > 0:
            stock_chg = (price_curr / price_ext - 1)
            val = (stock_chg - imoex_chg) * 100
            if pd.isna(val): return 0.0
            return val
        return 0.0
        
    df["rel_strength"] = df.apply(get_rel_strength, axis=1)
    df["score_strength"] = (df["rel_strength"] > 0).astype(int) * 100
    
    # 4. Дивиденды по рынку
    df["div_yield"] = df.apply(lambda r: (r["div_12m"] / r["PRICE"] * 100) if r["PRICE"] > 0 else 0.0, axis=1)
    df["score_div"] = df.apply(lambda r: 100 if r["div_yield"] > cb_rate else (50 if r["div_yield"] > 0 else 0), axis=1)
    
    # 5. Выплаты
    df["score_paid_12m"] = (df["div_12m"] > 0).astype(int) * 100
    
    # 6. Листинг
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)
    
    # 7. Индекс
    df["in_index"] = df["SECID"].isin(IMOEX_CONSTITUENTS)
    df["score_in_index"] = df["in_index"].astype(int) * 100
    
    # 8. Рекомендуемая цена
    df["recommended_price"] = df.apply(
        lambda r: round(r["div_12m"] / (cb_rate / 100), 2) if r["div_12m"] > 0 and cb_rate > 0 else 0.0, 
        axis=1
    )

    score_cols = [
        "score_w", "score_arsagera", "score_strength", 
        "score_div", "score_paid_12m", "score_dsi", 
        "score_list", "score_in_index"
    ]
    df["total_score"] = df[df.columns.intersection(score_cols)].sum(axis=1)
    return df

def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0: return "green"
    if div_yield > cb_rate and rel_strength <= 0: return "yellow"
    if div_yield == 0 and rel_strength > 0: return "orange"
    return "red"
