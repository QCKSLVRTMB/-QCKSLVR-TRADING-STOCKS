from dataclasses import dataclass, field
import pandas as pd

@dataclass(slots=True)
class Instrument:
    ticker: str
    name: str = "-"
    lot_size: int = 1
    price: float = 0.0
    min_step: float = 0.01
    decimals: int = 2
    list_level: int = 1
    
    @property
    def point_value(self) -> float:
        return float(self.lot_size)

    @property
    def lot_value(self) -> float:
        return self.price * self.lot_size

    def round_price(self, p: float) -> float:
        if not self.min_step: return round(p, self.decimals)
        return round(round(p / self.min_step) * self.min_step, self.decimals)

def get_instrument(ticker, df_stocks) -> Instrument:
    if df_stocks is None or df_stocks.empty: return Instrument(ticker=ticker)
    row = df_stocks[df_stocks["SECID"] == ticker]
    if row.empty: return Instrument(ticker=ticker)
    r = row.iloc[0]
    return Instrument(
        ticker=ticker, name=r["SHORTNAME"], lot_size=int(r["LOTSIZE"]),
        price=float(r["PRICE"]), min_step=float(r["MINSTEP"]),
        decimals=int(r["DECIMALS"]), list_level=int(r["LISTLEVEL"])
    )
