import pandas as pd
from core.config import DEFAULT_CB_RATE

def calc_ranking(df: pd.DataFrame, state_w_forms: dict, cb_rate: float) -> pd.DataFrame:
    df = df.copy()
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    
    # 1. W-формация
    df["w_form"] = df["SECID"].map(state_w_forms).fillna("-")
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)
    
    # 2. Выше/ниже индекса (мок для демонстрации, нужна реальная логика с IMOEX)
    df["rel_strength"] = 0.0 
    df["score_strength"] = (df["rel_strength"] > 0).astype(int) * 100
    
    # 3. Дивиденды
    df["div_12m"] = 0.0
    df["div_yield"] = 0.0
    df["score_div"] = 0
    
    # 4. DSI и Листинг
    df["dsi"] = 0.50
    df["score_dsi"] = df["dsi"] * 100
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)
    
    # Итог
    score_cols = [c for c in df.columns if c.startswith("score_")]
    df["total_score"] = df[score_cols].sum(axis=1)
    return df

def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0: return "green"
    if div_yield > cb_rate and rel_strength <= 0: return "yellow"
    if div_yield == 0 and rel_strength > 0: return "orange"
    return "red"
