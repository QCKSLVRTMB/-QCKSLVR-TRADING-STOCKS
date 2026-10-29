from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from core.config import TARIFF_CONFIGS

# ======================================================================
#  INSTRUMENT (Для акций)
# ======================================================================
@dataclass(slots=True)
class Instrument:
    ticker: str
    name: str = "-"
    lot_size: int = 1
    price: float = 0.0
    min_step: float = 0.01
    decimals: int = 2
    list_level: int = 1
    issue_size: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def point_value(self) -> float:
        return float(self.lot_size)

    @property
    def lot_value(self) -> float:
        return self.price * self.lot_size

    def round_price(self, p: float) -> float:
        if not self.min_step:
            return round(p, self.decimals)
        return round(round(p / self.min_step) * self.min_step, self.decimals)

def get_instrument(ticker, df_stocks) -> Instrument:
    if df_stocks is None or df_stocks.empty: 
        return Instrument(ticker=ticker)
    row = df_stocks[df_stocks["SECID"] == ticker]
    if row.empty: 
        return Instrument(ticker=ticker)
    r = row.iloc[0]
    return Instrument(
        ticker=ticker, name=r["SHORTNAME"], lot_size=int(r["LOTSIZE"]),
        price=float(r["PRICE"]), min_step=float(r["MINSTEP"]),
        decimals=int(r["DECIMALS"]), list_level=int(r["LISTLEVEL"])
    )

# ======================================================================
#  РАСЧЕТ СДЕЛКИ
# ======================================================================
def commission_per_side(inst: Instrument, price: float, tariff_name: str) -> float:
    # Упрощенный расчет комиссии для акций
    cfg = TARIFF_CONFIGS.get(tariff_name) or {"broker_percent": 0.0005}
    fee = price * inst.point_value * cfg["broker_percent"]
    return max(fee, 0.01) # Минимальная комиссия

def calc_avg_entry(entries: list[dict], default_price: float) -> tuple[float, int]:
    s_pq = s_q = s_p = 0.0
    cnt = 0
    for e in entries or []:
        p = float(e.get("price") or 0)
        if p <= 0: continue
        q = int(e.get("qty") or 0)
        s_pq += p * q
        s_q += q
        s_p += p
        cnt += 1
    if not cnt: return default_price, 0
    if s_q == 0: return s_p / cnt, 0
    return s_pq / s_q, int(s_q)

def plan_trade(inst: Instrument, *, direction: str, entries: list[dict], sl: float | None, tp: float | None, deposit: float, tariff: str) -> dict:
    entry, user_qty = calc_avg_entry(entries, inst.price)
    
    # Стоимость 1 лота
    lot_val = entry * inst.lot_size
    
    # Максимальное количество лотов на депозит
    qty_by_margin = int(deposit // lot_val) if lot_val > 0 else 0
    qty = user_qty if user_qty > 0 else qty_by_margin
    
    total_value = lot_val * qty
    fee_entry = commission_per_side(inst, entry, tariff) * qty
    
    return {
        "entry": entry, "sl": sl, "tp": tp, "qty": qty,
        "notional": total_value, "fee": fee_entry,
        "margin_total": total_value, # Для акций ГО = стоимость
    }

# ======================================================================
#  АНАЛИТИКА ГРАФИКОВ И ОБЪЕМОВ
# ======================================================================
class _Bars:
    __slots__ = ("idx", "high", "low", "vol", "cvol")
    def __init__(self, df: pd.DataFrame):
        self.idx = df.index
        self.high = df["High"].to_numpy(dtype="float64", copy=False)
        self.low = df["Low"].to_numpy(dtype="float64", copy=False)
        self.vol = df["Volume"].to_numpy(dtype="float64", copy=False)
        self.cvol = np.concatenate(([0.0], np.cumsum(self.vol)))

    def span(self, t0, t1) -> tuple[int, int]:
        i0 = int(self.idx.searchsorted(t0, side="left"))
        i1 = int(self.idx.searchsorted(t1, side="right"))
        return i0, max(i0, i1)

    def vsum(self, i0: int, i1: int) -> float:
        return float(self.cvol[i1] - self.cvol[i0])

def calculate_breakout_metrics(df, resistance_price, start_time, end_time, is_up=True):
    b = df if isinstance(df, _Bars) else _Bars(df)
    i0, i1 = b.span(start_time, end_time)
    if i1 <= i0: return 0, 0, start_time
    mask = (b.high[i0:i1] > resistance_price) if is_up else (b.low[i0:i1] < resistance_price)
    k = int(mask.argmax()) if mask.any() else None
    if k is None: brk_i, brk_time = i0, start_time
    else: brk_i = i0 + k; brk_time = b.idx[brk_i]
    j0, j1 = b.span(brk_time, end_time) if k is not None else (i0, i1)
    return j1 - j0, b.vsum(j0, j1), brk_time

def analyze_manual_zigzag(pts, df):
    if not pts or len(pts) < 4 or df is None or df.empty: return []
    b = _Bars(df)
    nodes = sorted(((pd.to_datetime(p[0]), float(p[1])) for p in pts), key=lambda x: x[0])
    breakouts = []
    
    for i in range(3, len(nodes)):
        (a_t, a_p), (b_t, b_p), (c_t, c_p), (d_t, d_p) = nodes[i - 3:i + 1]

        if a_p < b_p and a_p < c_p < b_p and d_p > b_p: s, trend = 1, "up"
        elif a_p > b_p and b_p < c_p < a_p and d_p < b_p: s, trend = -1, "down"
        else: continue

        bars, vol, brk_time = calculate_breakout_metrics(b, b_p, c_t, d_t, is_up=(s > 0))
        curr_height = s * (d_p - c_p)
        prev_height = s * (b_p - a_p)
        setup_delta = s * (b_p - c_p)

        p0, p1 = b.span(a_t, b_t)
        c0, c1 = b.span(c_t, d_t)
        s0, s1 = b.span(b_t, c_t)
        prev_bars, curr_bars = p1 - p0, c1 - c0
        prev_vol = b.vsum(p0, p1)

        height_ratio = curr_height / prev_height if prev_height > 0 else 0
        bars_ratio = curr_bars / prev_bars if prev_bars > 0 else 0
        vol_ratio = b.vsum(c0, c1) / prev_vol if prev_vol > 0 else 0
        breakout_pct = (curr_height / setup_delta * 100) if setup_delta > 0 else 0

        if height_ratio >= 1.1 and bars_ratio <= 1.0: verdict = "strong"
        elif height_ratio <= 0.9 or bars_ratio >= 1.5 or vol_ratio >= 1.5: verdict = "weak"
        else: verdict = "normal"

        breakouts.append({
            "trend": trend, "resistance_time": b_t, "resistance_price": b_p,
            "pullback_setup_time": c_t, "pullback_setup_price": c_p,
            "peak_time": d_t, "peak_price": d_p, "breakout_time": brk_time,
            "delta": curr_height, "breakout_pct": breakout_pct, "bars": bars, "volume": vol,
            "setup_delta": setup_delta, "setup_bars": s1 - s0, "setup_vol": b.vsum(s0, s1),
            "height_ratio": height_ratio, "bars_ratio": bars_ratio,
            "vol_ratio": vol_ratio, "breakout_verdict": verdict,
        })
    return breakouts

def _anomaly_color(tf_name: str) -> str | None:
    return {"M10": "red", "M1": "red", "H1": "green", "D1": "blue", "W": "purple"}.get(tf_name)

def get_volume_colors(df, tf_name, sensitivity=3.0):
    if df is None or df.empty or "Volume" not in df.columns: return []
    v = df["Volume"].to_numpy(dtype="float64", copy=False)
    n = v.size
    colors = np.full(n, "gray", dtype=object)

    if n > 2:
        m = np.zeros(n, dtype=bool)
        m[2:] = (v[2:] > v[1:-1]) & (v[2:] > v[:-2])
        colors[m] = "black"

    anomaly = _anomaly_color(tf_name)
    if anomaly and n:
        avg = (pd.Series(v).rolling(20, min_periods=5).mean().shift(1).to_numpy(dtype="float64"))
        with np.errstate(invalid="ignore"):
            mask = np.isfinite(avg) & (avg > 0) & (v > avg * sensitivity)
        colors[mask] = anomaly
    return colors.tolist()

def calculate_volume_profile(df, tf_name="M10", threshold_pct=50, sensitivity=3.0, colors=None):
    if df is None or df.empty or "Volume" not in df.columns: return []
    colors = np.asarray(colors if colors is not None else get_volume_colors(df, tf_name, sensitivity), dtype=object)
    if colors.size != len(df): return []

    anomaly = _anomaly_color(tf_name)
    mask = (colors == "black") | ((colors == anomaly) if anomaly else False)
    if not mask.any(): return []

    o = df["Open"].to_numpy(dtype="float64", copy=False)[mask]
    c = df["Close"].to_numpy(dtype="float64", copy=False)[mask]
    h = df["High"].to_numpy(dtype="float64", copy=False)[mask]
    l = df["Low"].to_numpy(dtype="float64", copy=False)[mask]
    vol = df["Volume"].to_numpy(dtype="float64", copy=False)[mask]

    is_buy = c > o
    low = np.where(is_buy, l, c)
    high = np.where(is_buy, c, h)
    ok = (high > low) & (vol > 0)
    low, high, vol = low[ok], high[ok], vol[ok]
    if low.size == 0: return []

    edges = np.unique(np.concatenate((low, high)))
    if edges.size < 2: return []

    diff = np.zeros(edges.size, dtype="float64")
    np.add.at(diff, np.searchsorted(edges, low), vol)
    np.add.at(diff, np.searchsorted(edges, high), -vol)
    band_vol = np.cumsum(diff)[:-1]

    keep = band_vol > 0
    if not keep.any(): return []

    max_vol, min_vol = float(band_vol[keep].max()), float(band_vol[keep].min())
    if max_vol > min_vol: threshold = min_vol + (max_vol - min_vol) * (int(threshold_pct) - 10) / 90.0
    else: threshold = min_vol

    sel = keep & (band_vol >= threshold)
    if not sel.any(): return []

    if max_vol > threshold: opacity = 0.15 + 0.45 * (band_vol - threshold) / (max_vol - threshold)
    else: opacity = np.full(band_vol.size, 0.60)

    out, i, idx = [], 0, np.flatnonzero(sel)
    while i < idx.size:
        j = i
        while (j + 1 < idx.size and idx[j + 1] == idx[j] + 1 and band_vol[idx[j + 1]] == band_vol[idx[j]]): j += 1
        out.append({"low": float(edges[idx[i]]), "high": float(edges[idx[j] + 1]), "opacity": float(opacity[idx[i]])})
        i = j + 1
    return out
