import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from core.config import INDEX_META
from core.market import fetch_moex_indices, fetch_extreme_close

def render_indices():
    st.subheader("Эффективность отраслевых индексов")
    df_idx = fetch_moex_indices()
    if df_idx.empty:
        st.warning("Нет данных по индексам.")
        return

    extreme_date = st.session_state.get("extreme_date", "20.07.2026")
    
    # Получаем IMOEX на экстремуме
    imoex_ext, imoex_date = fetch_extreme_close("IMOEX", extreme_date)
    
    if imoex_ext == 0:
        st.error(f"Не удалось получить данные IMOEX на {extreme_date}")
        return
        
    st.info(f"IMOEX на {imoex_date}: {imoex_ext:.2f} п. | Текущий: {df_idx[df_idx['SECID']=='IMOEX']['CURRENTVALUE'].values[0]:.2f} п.")
    
    rows = []
    imoex_curr = df_idx[df_idx['SECID']=='IMOEX']['CURRENTVALUE'].values[0]
    imoex_chg = (imoex_curr / imoex_ext - 1) * 100 if imoex_ext else 0
    
    for ticker, meta in INDEX_META.items():
        row = df_idx[df_idx['SECID'] == ticker]
        if row.empty: continue
        
        curr = row['CURRENTVALUE'].values[0]
        if curr == 0: continue
        
        ext, _ = fetch_extreme_close(ticker, extreme_date)
        if ext > 0:
            chg = (curr / ext - 1) * 100
            rel_strength = chg - imoex_chg
            rows.append({
                "ticker": ticker, "name": meta["name"], "color": meta["color"],
                "ext": ext, "curr": curr, "chg": chg, "rel": rel_strength
            })
            
    df = pd.DataFrame(rows)
    if df.empty: return
    
    # Строим график
    fig = go.Figure()
    for _, r in df.iterrows():
        fig.add_trace(go.Bar(
            x=[r["name"]], y=[r["rel"]], name=r["name"],
            marker_color=r["color"], marker_line_color='black', marker_line_width=1 if r["color"]=="#FFFFFF" else 0,
            text=f"{r['rel']:.2f}%", textposition="outside"
        ))
        
    fig.update_layout(
        title="Относительная сила секторов (к IMOEX)",
        showlegend=False, plot_bgcolor="white", height=500,
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="lightgray", zeroline=True, zerolinecolor="black")
    )
    st.plotly_chart(fig, use_container_width=True)
