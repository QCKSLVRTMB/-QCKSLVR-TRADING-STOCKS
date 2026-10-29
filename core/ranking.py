import pandas as pd
import re
import difflib
from core.market import fetch_extreme_close, fetch_dividends_dohod
from core import state
from core.config import DEFAULT_ARSAGERA_GROUPS, DEFAULT_W_FORMATIONS

IMOEX_CONSTITUENTS = {
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "TATN", "GMKN", "PLZL", 
    "YNDX", "OZON", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "MTSS", 
    "MGNT", "MOEX", "PHOR", "SNGS", "TATNP", "TRNFP", "AFKS", "RTKM"
}

def normalize_name(s):
    """Убирает пробелы, кавычки и знаки препинания для корректного сравнения"""
    return re.sub(r'[^А-ЯЁA-Z0-9]', '', str(s).upper())

def get_whitelist(df_stocks, ars_data, dohod_data):
    """Возвращает список тикеров, которые есть в Арсагере или в Доходе"""
    ars_tickers = set(ars_data.keys())
    dohod_names_clean = {normalize_name(n): n for n in dohod_data.keys()}
    
    whitelist = []
    for _, row in df_stocks.iterrows():
        secid = row["SECID"]
        clean_shortname = normalize_name(row["SHORTNAME"])
        
        # 1. Прямое совпадение тикера в Арсагере
        if secid in ars_tickers:
            whitelist.append(secid)
            continue
            
        # 2. Точное совпадение названия в Доходе
        if clean_shortname in dohod_names_clean:
            whitelist.append(secid)
            continue
            
        # 3. Частичное совпадение названия (например, "Сбербанк" и "Сбербанк России")
        matched = False
        for clean_d in dohod_names_clean.keys():
            if clean_shortname in clean_d or clean_d in clean_shortname:
                whitelist.append(secid)
                matched = True
                break
        if matched: continue
            
        # 4. Нечеткое совпадение (Fuzzy)
        matches = difflib.get_close_matches(clean_shortname, list(dohod_names_clean.keys()), n=1, cutoff=0.85)
        if matches:
            whitelist.append(secid)
            
    return whitelist

def calc_ranking(df: pd.DataFrame, state_w_forms: dict, cb_rate: float, closes_on_extreme: dict, imoex_ext: float, imoex_curr: float) -> pd.DataFrame:
    df = df.copy()
    
    # 1. W-формация
    user_w = state_w_forms if isinstance(state_w_forms, dict) else {}
    w_forms = {**DEFAULT_W_FORMATIONS, **user_w}
    w_scores = {"вверх": 100, "рейндж": 50, "вниз": 0}
    df["w_form"] = df["SECID"].map(w_forms).fillna("-")
    df["score_w"] = df["w_form"].map(w_scores).fillna(0)
    
    # 2. Арсагера
    user_ars = state.g("arsagera_groups")
    if not isinstance(user_ars, dict): user_ars = {}
    combined_ars = {**DEFAULT_ARSAGERA_GROUPS, **user_ars}
        
    ars_scores = {1: 100, 2: 75, 3: 50, 4: 25}
    df["ars_group"] = df["SECID"].map(combined_ars).fillna(0).astype(int)
    df["score_arsagera"] = df["ars_group"].map(ars_scores).fillna(0)
    
    # 3. Сила актива
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
    
    # 4. Дивиденды
    dohod_data = state.g("dohod_data", {})
    dohod_names_clean = {normalize_name(n): data for n, data in dohod_data.items()}
    
    def get_div_data(row):
        ticker = row["SECID"]
        clean_shortname = normalize_name(row["SHORTNAME"])
        
        if clean_shortname in dohod_names_clean:
            data = dohod_names_clean[clean_shortname]
            return data["div"], data["dsi"]
            
        for clean_d, data in dohod_names_clean.items():
            if clean_shortname in clean_d or clean_d in clean_shortname:
                return data["div"], data["dsi"]
                
        # Если нет в файле, идем в интернет
        res = fetch_dividends_dohod(ticker)
        return res.get("div_12m", 0.0), res.get("dsi", 0.0)

    div_data = df.apply(get_div_data, axis=1)
    df["div_12m"] = [x[0] for x in div_data]
    df["dsi"] = [x[1] for x in div_data]
    
    df["div_yield"] = df.apply(lambda r: (r["div_12m"] / r["PRICE"] * 100) if r["PRICE"] > 0 else 0.0, axis=1)
    df["score_div"] = df.apply(lambda r: 100 if r["div_yield"] > cb_rate else (50 if r["div_yield"] > 0 else 0), axis=1)
    
    # 5. Выплаты
    df["score_paid_12m"] = (df["div_12m"] > 0).astype(int) * 100
    
    # 6. DSI
    df["dsi"] = df["dsi"].clip(upper=1.0)
    df["score_dsi"] = df["dsi"].fillna(0) * 100
    
    # 7. Листинг
    list_scores = {1: 100, 2: 70, 3: 40}
    df["score_list"] = df["LISTLEVEL"].map(list_scores).fillna(0)
    
    # 8. Индекс
    df["in_index"] = df["SECID"].isin(IMOEX_CONSTITUENTS)
    df["score_in_index"] = df["in_index"].astype(int) * 100
    
    # 9. Рекомендуемая цена
    df["recommended_price"] = df.apply(
        lambda r: round(r["div_12m"] / (cb_rate / 100), 2) if r["div_12m"] > 0 and cb_rate > 0 else 0.0, 
        axis=1
    )

    score_cols = [
        "score_w", "score_arsagera", "score_strength", 
        "score_div", "score_paid_12m", "score_dsi", 
        "score_list", "score_in_index"
    ]
    df["total_score"] = df[score_cols].sum(axis=1)
    return df

def get_asset_color(div_yield: float, cb_rate: float, rel_strength: float) -> str:
    if div_yield > cb_rate and rel_strength > 0: return "green"
    if div_yield <= cb_rate and rel_strength > 0: return "orange"
    if div_yield > cb_rate and rel_strength <= 0: return "yellow"
    return "red"
