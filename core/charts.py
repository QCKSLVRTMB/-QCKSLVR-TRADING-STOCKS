from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from core.calc import get_volume_colors

GREEN  = "#26a69a"
RED    = "#ef5350"
BLUE   = "#1976D2"
PURPLE = "#7B1FA2"
BAR_LINE_COLOR = "#000000"

def _ts(x) -> pd.Timestamp: return pd.to_datetime(x)
def sort_points(points: list) -> list: return sorted((p for p in points if p), key=lambda p: _ts(p[0]))

def _add_shapes(fig, shapes):
    if shapes: fig.update_layout(shapes=list(fig.layout.shapes) + shapes)

def _add_annots(fig, annots):
    if annots: fig.update_layout(annotations=list(fig.layout.annotations) + annots)

def _sh(x0, y0, x1, y1, color, dash=None, width=2, layer="above"):
    return dict(type="line", xref="x", yref="y", x0=x0, y0=y0, x1=x1, y1=y1, layer=layer, line=dict(color=color, width=width, dash=dash))

def _rect(x0, x1, y0, y1, fillcolor, layer="below"):
    return dict(type="rect", xref="x", yref="y", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=fillcolor, line=dict(width=0), layer=layer)

def draw_channel(fig, pts, x_right, color="blue"):
    if len(pts) < 3: return
    t_a, y_a = pts[0][:2]; t_b, y_b = pts[1][:2]; t_c, y_c = pts[2][:2]
    x_a, x_c = _ts(t_a), _ts(t_c)
    dt = (x_c - x_a).total_seconds() or 1
    k = (y_c - y_a) / dt
    y_c_ext = y_a + k * (_ts(x_right) - x_a).total_seconds()
    off = y_b - (y_a + k * (_ts(t_b) - x_a).total_seconds())

    shapes = [
        _sh(x_a, y_a, x_right, y_c_ext, color, width=2),
        _sh(x_a, y_a + off, x_right, y_c_ext + off, color, width=2),
    ]
    _add_shapes(fig, shapes)
    fillcolor = "rgba(123,31,162,0.08)" if color == "purple" else "rgba(25,118,210,0.08)"
    fig.add_trace(go.Scatter(x=[x_a, x_right, x_right, x_a], y=[y_a, y_c_ext, y_c_ext + off, y_a + off], fill="toself", fillcolor=fillcolor, line=dict(width=0), hoverinfo="skip", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=[x_a, _ts(t_b), x_c], y=[y_a, y_b, y_c], mode='markers+text', marker=dict(color=color, size=10), text=["A", "B", "C"], textposition="top center", showlegend=False), row=1, col=1)

def draw_fib(fig, pts, x_left, x_right, color, label):
    pts = sort_points(pts)
    if len(pts) < 2: return
    mid_price = (float(pts[0][1]) + float(pts[1][1])) / 2
    _add_shapes(fig, [_sh(x_left, mid_price, x_right, mid_price, color, dash="dash", width=2)])
    _add_annots(fig, [dict(xref="x", yref="y", x=x_right, y=mid_price, text=label, showarrow=False, xanchor="left", font=dict(color=color, size=10))])

def draw_zigzag(fig, pts, color, name):
    pts = sort_points(pts)
    if len(pts) < 2: return
    xs, ys = [_ts(p[0]) for p in pts], [float(p[1]) for p in pts]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", line=dict(color=color, width=3), marker=dict(size=8, color=color), name=name), row=1, col=1)

def draw_clusters(fig, clusters, x_left, x_right, color="orange"):
    base = "rgba(33,150,243," if color == "blue" else "rgba(251,140,0,"
    _add_shapes(fig, [_rect(x_left, x_right, cl["low"], cl["high"], f"{base}{cl['opacity']:.2f})") for cl in clusters])

def draw_trade_visuals(fig, buy_level, sell_level, x_left, x_right, decimals):
    shapes, annots = [], []
    if buy_level and buy_level > 0:
        shapes.append(_sh(x_left, buy_level, x_right, buy_level, "green", dash="dash", width=2))
        annots.append(dict(xref="x", yref="y", x=x_right, y=buy_level, text=f"Уровень покупок: {buy_level:,.{decimals}f}", showarrow=False, xanchor="right", bgcolor="rgba(25, 135, 84, 0.9)", font=dict(color="white", size=10)))
    if sell_level and sell_level > 0:
        shapes.append(_sh(x_left, sell_level, x_right, sell_level, "red", dash="dash", width=2))
        annots.append(dict(xref="x", yref="y", x=x_right, y=sell_level, text=f"Уровень продаж: {sell_level:,.{decimals}f}", showarrow=False, xanchor="right", bgcolor="rgba(220, 53, 69, 0.9)", font=dict(color="white", size=10)))
    _add_shapes(fig, shapes)
    _add_annots(fig, annots)

def build_figure(df, *, tf_name, title, decimals, mobile, show_info=True):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.8, 0.2])
    df = df.copy()
    df["Change"] = df["Close"].pct_change() * 100
    
    hover_temp = None
    hoverlabel = None
    if show_info:
        hover_temp = (f"%{{x|%d.%m.%Y %H:%M}}<br>О: %{{open:.{decimals}f}}<br>В: %{{high:.{decimals}f}}<br>Н: %{{low:.{decimals}f}}<br>З: %{{close:.{decimals}f}}<br>Изм: %{{customdata[0]:+.2f}}%<br>Вол: %{{customdata[1]:,.0f}}<extra></extra>")
        h_bg = "rgba(25,118,210,0.95)" if tf_name in ["D1", "W"] else ("rgba(38,166,154,0.95)" if tf_name == "H1" else "rgba(239,83,80,0.95)")
        hoverlabel = dict(bgcolor=h_bg, font=dict(color="white", size=10), align="left")

    fig.add_trace(go.Ohlc(
        x=df.index.to_numpy(), open=df["Open"].to_numpy(), high=df["High"].to_numpy(), low=df["Low"].to_numpy(), close=df["Close"].to_numpy(), 
        increasing_line_color=BAR_LINE_COLOR, decreasing_line_color=BAR_LINE_COLOR, 
        increasing_line_width=1.5, decreasing_line_width=1.5, name="",
        customdata=df[["Change", "Volume"]].to_numpy(), hovertemplate=hover_temp
    ), row=1, col=1)
    
    if "Volume" in df.columns:
        colors = get_volume_colors(df, tf_name, sensitivity=3.0)
        fig.add_trace(go.Bar(x=df.index.to_numpy(), y=df["Volume"].to_numpy(), marker_color=colors, name="Объем", hoverinfo="skip"), row=2, col=1)
        
    breaks = [dict(bounds=["sat", "mon"])]
    if tf_name != "D1" and tf_name != "W": breaks.append(dict(bounds=[23.833, 7], pattern="hour"))
    time_buffer = pd.Timedelta(days=10) if tf_name in ["D1", "W"] else (pd.Timedelta(hours=12) if tf_name == "H1" else pd.Timedelta(hours=2))
    
    fig.update_xaxes(rangeslider_visible=False, rangebreaks=breaks, range=[df.index[0] - pd.Timedelta(hours=4), df.index[-1] + time_buffer], showgrid=True, gridcolor="lightgray", showspikes=True, spikemode="across", spikesnap="cursor", spikecolor="black", spikethickness=1, spikedash="dot")
    fig.update_yaxes(side="right", tickformat=f".{decimals}f", showgrid=True, gridcolor="lightgray", showspikes=True, spikemode="across", spikesnap="cursor", spikecolor="black", spikethickness=1, spikedash="dot", row=1, col=1)
    fig.update_yaxes(side="right", showgrid=True, gridcolor="lightgray", row=2, col=1)
    
    fig.update_layout(title=title, height=900 if mobile else 800, margin=dict(l=10, r=10, t=50, b=50), plot_bgcolor="white", paper_bgcolor="white", showlegend=False, hovermode="closest", hoverlabel=hoverlabel, dragmode="pan")
    return fig

PLOT_CONFIG = {"scrollZoom": True, "displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"], "doubleClick": "reset"}

def capture_click(chart_key: str) -> tuple[str, float] | None:
    ev = st.session_state.get(chart_key)
    if not isinstance(ev, dict): return None
    pts = (ev.get("selection") or {}).get("points") or []
    if not pts: return None
    p = pts[-1]; x, y = p.get("x"), p.get("y")
    if x is None or y is None: return None
    sig = f"{x}|{y}"
    store = st.session_state.setdefault("_click_sig", {})
    if store.get(chart_key) == sig: return None
    store[chart_key] = sig
    return str(x), float(y)
