"""Персистентность: схема v3, миграция, атомарная запись, debounce."""
from __future__ import annotations

import json, os, re, tempfile, time
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from core.config import SCHEMA_VERSION, DEFAULT_GLOBAL, TIMEFRAMES

CACHE_DIR = Path(os.getenv("FUTURES_CACHE_DIR", ".cache"))
PROFILE_RE = re.compile(r"[^A-Za-z0-9_\-а-яА-Я ]+")

def json_serializer(obj):
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)

def default_ticker_state() -> dict:
    return {
        "market": {"trend": "вверх", "wave": "вверх", "tendency": "вверх"},
        "charts": {tf: {"channel": [], "fib": [], "zigzag": [], "levels": [], "cluster_range": []} for tf in TIMEFRAMES},
        "buy_level": None,
        "sell_level": None,
        "entries": [],
        "note": "",
        "updated_at": None,
    }

def default_state() -> dict:
    return {"version": SCHEMA_VERSION, "saved_at": None, "global": dict(DEFAULT_GLOBAL), "tickers": {}}

def _norm_point(p: Any) -> list | None:
    try:
        if isinstance(p, dict):
            x, y = p.get("x"), p.get("y")
        else:
            x, y = p[0], p[1]
        if x is None or y is None: return None
        return [str(x), round(float(y), 8)]
    except Exception:
        return None

def normalize_points(points) -> list:
    return [q for q in (_norm_point(p) for p in (points or [])) if q]

def _normalize_ticker(raw: dict) -> dict:
    base = default_ticker_state()
    if not isinstance(raw, dict): return base
    
    base["market"].update({k: v for k, v in (raw.get("market") or {}).items() if v})
    
    charts_raw = raw.get("charts") or {}
    for tf in TIMEFRAMES:
        if tf not in base["charts"]: continue
        tools_raw = charts_raw.get(tf) or {}
        for tool in base["charts"][tf].keys():
            if tool in tools_raw:
                if tool == "levels":
                    base["charts"][tf]["levels"] = sorted({round(float(v), 8) for v in (tools_raw.get(tool) or []) if v is not None})
                else:
                    base["charts"][tf][tool] = normalize_points(tools_raw.get(tool))
                
    base["buy_level"] = raw.get("buy_level")
    base["sell_level"] = raw.get("sell_level")
    base["entries"] = [
        {"price": float(e.get("price", 0) or 0), "qty": int(e.get("qty", 0) or 0), "note": str(e.get("note", "") or "")}
        for e in (raw.get("entries") or []) if e
    ]
    base["note"] = str(raw.get("note", "") or "")
    base["updated_at"] = raw.get("updated_at")
    return base

def migrate(raw: dict) -> dict:
    if not isinstance(raw, dict): return default_state()
    st_ = default_state()
    st_["global"].update({k: v for k, v in (raw.get("global") or {}).items() if k in DEFAULT_GLOBAL})
    
    # Фильтруем None из ключей тикеров
    raw_tickers = raw.get("tickers") or {}
    st_["tickers"] = {str(k): _normalize_ticker(v) for k, v in raw_tickers.items() if k is not None}
    
    st_["saved_at"] = raw.get("saved_at")
    return st_

def profile_path(profile: str) -> Path:
    safe = PROFILE_RE.sub("", profile or "default").strip() or "default"
    return CACHE_DIR / f"{safe}.json"

def list_profiles() -> list[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in CACHE_DIR.glob("*.json")) or ["default"]

def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def load_profile(profile: str = "default") -> dict:
    path = profile_path(profile)
    if not path.exists(): return default_state()
    try:
        with path.open("r", encoding="utf-8") as f:
            return migrate(json.load(f))
    except Exception:
        return default_state()

def dumps(state: dict, pretty: bool = True) -> str:
    state = dict(state)
    state["version"] = SCHEMA_VERSION
    state["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    
    # На всякий случай приводим все ключи тикеров к строкам
    if "tickers" in state:
        state["tickers"] = {str(k): v for k, v in state["tickers"].items() if k is not None}

    return json.dumps(
        state, 
        ensure_ascii=False, 
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"), 
        sort_keys=True, 
        default=json_serializer
    )

def save_profile(state: dict, profile: str = "default") -> None:
    _atomic_write(profile_path(profile), dumps(state))

def loads(text: str) -> dict | None:
    try: return migrate(json.loads(text))
    except Exception: return None
