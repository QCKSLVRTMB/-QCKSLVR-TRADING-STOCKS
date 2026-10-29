import pandas as pd
from core.config import DEFAULT_CB_RATE

# Базовый список акций, входящих в IMOEX (для проверки "В составе индекса")
IMOEX_CONSTITUENTS = {
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "GMKN", "PLZL", 
    "YNDX", "OZON", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "MTSS", 
    "MGNT", "MOEX", "PHOR", "SNGS", "TATNP", "TRNFP", "AFKS", "RTKM"
}

def calc_ranking(df: pd.DataFrame, state_w_forms: dict, cb_rate: float) -> pd.DataFrame:
    df = df.copy()
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    
    # 1. W-формация
    df["w_form"] = df["SECID"].map(state_w_forms).fillna("-")
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)
    
    # 2. Выше/ниже индекса (мок для демонстрации)
    # В реальном коде здесь будет расчет relative_strength
    df["rel_strength"] = 0.0 
    df["score_strength"] = (df["rel_strength"] > 0).astype(int) * 100
    
    # 3. Дивиденды (мок для демонстрации)
    df["div_12m"] = 10.0
    df["div_yield"] = 5.0
    df["score_div"] = df.apply(lambda r: 100 if r["div_yield"] > cb_rate else (50 if r["div_yield"] > 0 else 0), axis=1)
    
    # 4. DSI и Листинг
    df["dsi"] = 0.50
    df["score_dsi"] = df["dsi"] * 100
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)
    
    # 5. В составе индекса
    df["in_index"] = df["SECID"].isin(IMOEX_CONSTITUENTS)
    
    # 6. Рекомендуемая цена
    df["recommended_price"] = df.apply(
        lambda r: round(r["div_12m"] / (cb_rate / 100), 2) if r["div_12m"] > 0 and cb_rate > 0 else 0.0, 
        axis=1
    )

    # Итог
    score_cols = [c for c in df.columns if c.startswith("score_")]
    df["total_score"] = df[score_cols].sum(axis=1)
    return df

def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0: return "green"
    if div_yield > cb_rate and rel_strength <= 0: return "yellow"
    if div_yield == 0 and rel_strength > 0: return "orange"
    return "red"
