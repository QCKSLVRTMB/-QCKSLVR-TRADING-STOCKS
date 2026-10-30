"""Парсер Источники.xlsx — 3 листа: Арсагера (4 блока), ДОХОД DSI, W-формации."""
import re
import pandas as pd


# ---------- Утилиты ----------
def _normalize(text) -> str:
    if pd.isna(text):
        return ""
    return re.sub(r'[^\wа-яё]', '', str(text).strip().lower(), flags=re.IGNORECASE)


def _split_share_class(raw) -> tuple:
    """'Сургутнефтегаз-ао' → ('сургутнефтегаз','common')
       'Татнефть, ап'     → ('татнефть','preferred')
       'ЛУКОЙЛ'           → ('лукойл','common')"""
    if pd.isna(raw):
        return "", "common"
    s_raw = str(raw).strip().lower()
    s_norm = _normalize(s_raw)
    if not s_norm:
        return "", "common"
    for pat in ('-pref', ' pref', '-ап', ', ап', ' ап', '-п', ' п'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _normalize(pat)
            if m and s_norm.endswith(m):
                return s_norm[:-len(m)], 'preferred'
            return s_norm, 'preferred'
    for pat in ('-ord', ' ord', '-ао', ' ао', '-ao', ' ao'):
        if s_raw.endswith(pat) and len(s_raw) > len(pat):
            m = _normalize(pat)
            if m and s_norm.endswith(m):
                return s_norm[:-len(m)], 'common'
            return s_norm, 'common'
    return s_norm, 'common'


def _lookup_ticker(name, name_index: dict):
    base, cls = _split_share_class(name)
    if not base:
        return None
    t = name_index.get((base, cls))
    if t:
        return t
    # prefix match
    best, best_len = None, 0
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb:
            continue
        if nb.startswith(base) or base.startswith(nb):
            overlap = min(len(nb), len(base))
            if overlap >= 4 and overlap > best_len:
                best, best_len = ticker, overlap
    if best:
        return best
    # substring match
    for (nb, nc), ticker in name_index.items():
        if nc != cls or not nb:
            continue
        if (base in nb or nb in base) and min(len(base), len(nb)) >= 3:
            return ticker
    return None


# ---------- Лист 1 ----------
def parse_arsagera(path: str):
    df = pd.read_excel(path, sheet_name='Рейтинг арсагера', header=None)
    BLOCKS = [  # (ticker_col, name_col, rank_col, group, score)
        (0,  1,  3,  1, 100),
        (5,  6,  8,  2,  75),
        (10, 11, 13, 3,  50),
        (15, 16, 18, 4,  25),
    ]
    by_ticker, name_index = {}, {}
    for tcol, ncol, rcol, grp, score in BLOCKS:
        if tcol >= df.shape[1]:
            continue
        for _, row in df.iterrows():
            t_raw = row.iloc[tcol] if tcol < len(row) else None
            n_raw = row.iloc[ncol] if ncol < len(row) else None
            if pd.isna(t_raw) or pd.isna(n_raw):
                continue
            ticker = str(t_raw).strip().upper()
            if ticker in {'ТИКЕР', 'TICKER', 'NAN'}:
                continue
            if not re.match(r'^[A-ZА-Я0-9]{1,10}$', ticker):
                continue
            name = str(n_raw).strip()
            if not name or ticker in by_ticker:
                continue
            by_ticker[ticker] = {'name': name, 'group': grp, 'score': score}
            base, cls = _split_share_class(name)
            if base:
                name_index.setdefault((base, cls), ticker)
    return by_ticker, name_index


# ---------- Лист 2 ----------
def parse_dsi(path: str, name_index: dict) -> dict:
    try:
        df = pd.read_excel(path, sheet_name='ДОХОД DSI', header=None)
    except Exception as e:
        print(f'[DSI] sheet not readable: {e}')
        return {}
    result = {}
    for _, row in df.iterrows():
        name  = row.iloc[1] if len(row) > 1 else None
        value = row.iloc[6] if len(row) > 6 else None
        if pd.isna(name) or pd.isna(value):
            continue
        if not isinstance(value, (int, float)):
            continue
        ticker = _lookup_ticker(name, name_index)
        if ticker and ticker not in result:
            result[ticker] = round(float(value) * 100, 2)
    return result


# ---------- Лист 3 ----------
def parse_w_formations(path: str) -> dict:
    try:
        df = pd.read_excel(path, sheet_name='W-формации', header=None)
    except Exception as e:
        print(f'[W] sheet not readable: {e}')
        return {}
    ALIASES = {
        'вверх': 'вверх', 'up': 'вверх', 'рост': 'вверх',
        'вниз':  'вниз',  'down': 'вниз', 'падение': 'вниз',
        'рейндж': 'рейндж', 'range': 'рейндж', 'боковик': 'рейндж',
    }
    result = {}
    for _, row in df.iterrows():
        t_raw = row.iloc[0] if len(row) > 0 else None
        d_raw = row.iloc[1] if len(row) > 1 else None
        if pd.isna(t_raw) or pd.isna(d_raw):
            continue
        ticker = str(t_raw).strip().upper()
        if ticker in {'ТИКЕР', 'TICKER', 'NAN'} or not re.match(r'^[A-ZА-Я0-9]{1,10}$', ticker):
            continue
        direction = str(d_raw).strip().lower()
        if direction in ALIASES:
            result[ticker] = ALIASES[direction]
    return result


# ---------- Точка входа ----------
def load_sources(path: str) -> dict:
    ars, name_index = parse_arsagera(path)
    dsi = parse_dsi(path, name_index)
    w   = parse_w_formations(path)
    print(f'[load_sources] arsagera={len(ars)} dsi={len(dsi)} w={len(w)}')
    return {'arsagera': ars, 'dsi': dsi, 'w': w}
