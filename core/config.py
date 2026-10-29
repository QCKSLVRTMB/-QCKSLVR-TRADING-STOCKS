from __future__ import annotations

SCHEMA_VERSION = 5 # Версия обновлена
APP_TITLE = "Калькулятор акций MOEX"

TREND_VALUES = ["вверх", "вниз", "рейндж"]
DIRECTIONS = ["LONG", "SHORT"]

DEFAULT_EXTREME_DATE = "20.07.2026"
DEFAULT_CB_RATE = 14.00
DEFAULT_CASH_RESERVE = 20.0
DEFAULT_TAX_RATE = 13.0

INTERVALS = {
    "W":   {"interval": 7,  "days_back": 3650, "is_intraday": False, "label": "W (Недели)"},
    "D1":  {"interval": 24, "days_back": 730,  "is_intraday": False, "label": "D1 (Дни)"},
    "H1":  {"interval": 60, "days_back": 730,  "is_intraday": True,  "label": "H1 (Часы)"},
}
TIMEFRAMES = list(INTERVALS.keys())

TOOLS = {
    "channel": "Канал",
    "fib_w": "Уровень 1/2 (W)",
    "fib_d1": "Уровень 1/2 (D1)",
    "fib_h1": "Уровень 1/2 (H1)",
    "zigzag": "Зигзаг",
    "cluster_range": "Диапазон кластеров"
}

TARIFF_CONFIGS = {
    "Т-Инвестиции": {"type": "percent", "broker_percent": 0.0004, "min_fee": 0.01},
    "Финам": {"type": "percent", "broker_percent": 0.0003, "min_fee": 0.01},
    "Без комиссии": {"type": "percent", "broker_percent": 0.0, "min_fee": 0.0},
}

INDEX_META = {
    "MOEXCH": {"name": "Химия", "color": "#8BC34A"},
    "MOEXCN": {"name": "Потребительский", "color": "#FF0000"},
    "MOEXEU": {"name": "Энергетика", "color": "#1976D2"},
    "MOEXFN": {"name": "Финансы", "color": "#009688"},
    "MOEXINN": {"name": "Инновации", "color": "#673AB7"},
    "MOEXIT": {"name": "IT-сектор", "color": "#FFEB3B"},
    "MOEXMM": {"name": "Металлы и добыча", "color": "#9E9E9E"},
    "MOEXOG": {"name": "Нефтегазовый", "color": "#FFC107"},
    "MOEXRE": {"name": "Строительство", "color": "#FF00FF"},
    "MOEXTN": {"name": "Транспорт", "color": "#03A9F4"},
    "MREDC":  {"name": "Недвижимость", "color": "#FFFFFF"},
}

# Дефолтные W-формации
DEFAULT_W_FORMATIONS = {
    "ABIO": "вверх", "ABRD": "вверх", "AFKS": "вниз", "AFLT": "вверх", 
    "AKRN": "вверх", "ALRS": "вверх", "AMEZ": "вверх", "APTK": "вниз",
    "GAZP": "вниз", "SBER": "вверх", "LKOH": "вверх", "TATN": "вверх",
    "ROSN": "вниз", "NVTK": "вверх", "SIBN": "вверх", "TRNFP": "вверх"
}

# Дефолтные группы Арсагеры (1, 2, 3, 4). Если тикера нет - 0 баллов.
DEFAULT_ARSAGERA_GROUPS = {
    "LKOH": 1, "SBER": 1, "GAZP": 1, "ROSN": 1, "TATN": 1, "NVTK": 1
}

DEFAULT_GLOBAL = {
    "extreme_date": DEFAULT_EXTREME_DATE,
    "cb_rate": DEFAULT_CB_RATE,
    "cash_reserve": DEFAULT_CASH_RESERVE,
    "tax_rate": DEFAULT_TAX_RATE,
    "deposit": 100000,
    "mobile_view": False,
    "active_tickers": [],
    "w_formations": DEFAULT_W_FORMATIONS,
    "arsagera_groups": DEFAULT_ARSAGERA_GROUPS,
    "sector_weights": {"Нефтегаз": 35, "Финансы": 25, "Металлы": 30, "Разное": 10},
    "portfolio_data": [] 
}
