import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from core import state
from core.market import fetch_moex_stocks, fetch_moex_candles, fetch_moex_indices, fetch_extreme_close
from core.config import INDEX_META
from core.calc import get_instrument

def render_dashboard(df_stocks: pd.DataFrame):
    st.subheader("Дашборд портфеля")
    
    positions = state.g("portfolio_data", [])
    cash = state.g("portfolio_cash", 0.0)
    
    if not positions:
        st.info("Загрузите портфель для отображения дашборда.")
        return

    # --- Сбор данных для портфеля ---
    rows = []
    total_stocks_val = 0.0
    for p in positions:
        t = p["Тикер"]
        avg_price = float(p["ТВХ"])
        lots = int(p["Лотов"])
        
        inst = get_instrument(t, df_stocks)
        current_price = inst.price if inst.price > 0 else avg_price
        lot_size = inst.lot_size if inst.lot_size > 0 else 1
        shares = lots * lot_size
        
        val = current_price * shares
        cost = avg_price * shares
        pl_pct = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0.0
        
        total_stocks_val += val
        rows.append({
            "Тикер": t,
            "Название": inst.name,
            "Стоимость": val,
            "Вложено": cost,
            "P/L %": pl_pct
        })
        
    df_port = pd.DataFrame(rows)
    total_portfolio_val = total_stocks_val + cash

    # ============================================================
    # 1. СОСТАВ ПОРТФЕЛЯ (Кольцевая диаграмма)
    # ============================================================
    st.markdown("### Состав портфеля по бумагам")
    
    labels = df_port["Название"].tolist()
    values = df_port["Стоимость"].tolist()
    
    if cash > 0:
        labels.append("Рубли (Кеш)")
        values.append(cash)
        
    fig_pie = go.Figure(data=[go.Pie(
        labels=labels, 
        values=values, 
        hole=.5,
        textinfo='label+percent',
        insidetextorientation='radial'
    )])
    fig_pie.update_layout(
        showlegend=True, 
        height=500,
        margin=dict(t=30, b=30, l=30, r=30)
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    # ============================================================
    # 2. БЕНЧМАРКИНГ (Сравнение с IMOEX)
    # ============================================================
    st.markdown("### Бенчмаркинг")
    st.caption("Сравнение динамики портфеля с индексом Московской Биржи (IMOEX) за последние 6 месяцев.")
    
    with st.spinner("Загрузка данных IMOEX..."):
        df_imoex = fetch_moex_candles("IMOEX", interval=24, days_back=180, market="index")
        
    if not df_imoex.empty:
        base_price = df_imoex['Close'].iloc[0]
        df_imoex['Return %'] = (df_imoex['Close'] / base_price - 1) * 100
        
        port_return = (total_stocks_val / df_port["Вложено"].sum() - 1) * 100 if df_port["Вложено"].sum() > 0 else 0.0
        
        fig_bench = go.Figure()
        fig_bench.add_trace(go.Scatter(
            x=df_imoex.index, y=df_imoex['Return %'], 
            mode='lines', name='IMOEX', line=dict(color='#1976D2', width=2)
        ))
        
        fig_bench.add_trace(go.Scatter(
            x=[df_imoex.index[0], df_imoex.index[-1]], 
            y=[port_return, port_return], 
            mode='lines', name='Портфель (тек. P/L)', line=dict(color='#26a69a', width=2, dash='dash')
        ))
        
        fig_bench.update_layout(
            height=400,
            margin=dict(t=30, b=30, l=30, r=30),
            plot_bgcolor="white",
            yaxis=dict(title="Доходность, %", showgrid=True, gridcolor="lightgray"),
            xaxis=dict(showgrid=True, gridcolor="lightgray"),
            hovermode="x unified"
        )
        st.plotly_chart(fig_bench, use_container_width=True)
    else:
        st.warning("Не удалось загрузить данные IMOEX для графика.")

    # ============================================================
    # 3. ИНДЕКСЫ (Эффективность секторов)
    # ============================================================
    st.markdown("### Эффективность отраслевых индексов")
    df_indices = fetch_moex_indices()
    extreme_date = state.g("extreme_date")
    
    if not df_indices.empty:
        imoex_ext, _ = fetch_extreme_close("IMOEX", extreme_date, market="index")
        imoex_row = df_indices[df_indices['SECID'] == 'IMOEX']
        imoex_curr = imoex_row['CURRENTVALUE'].values[0] if not imoex_row.empty else 0
        
        if imoex_ext > 0 and imoex_curr > 0:
            imoex_chg = (imoex_curr / imoex_ext - 1) * 100
            
            idx_rows = []
            for ticker, meta in INDEX_META.items():
                row = df_indices[df_indices['SECID'] == ticker]
                if row.empty: continue
                curr = row['CURRENTVALUE'].values[0]
                if curr == 0: continue
                
                ext, _ = fetch_extreme_close(ticker, extreme_date)
                if ext > 0:
                    chg = (curr / ext - 1) * 100
                    idx_rows.append({
                        "name": meta["name"], 
                        "color": meta["color"],
                        "rel": chg - imoex_chg
                    })
                    
            if idx_rows:
                df_idx = pd.DataFrame(idx_rows).sort_values("rel", ascending=False)
                fig_idx = go.Figure(go.Bar(
                    x=df_idx["name"], y=df_idx["rel"],
                    marker_color=df_idx["color"],
                    text=df_idx["rel"].apply(lambda x: f"{x:.2f}%"),
                    textposition="outside"
                ))
                fig_idx.update_layout(
                    height=400,
                    plot_bgcolor="white",
                    yaxis=dict(showgrid=True, gridcolor="lightgray", title="Отн. сила, %"),
                    xaxis=dict(showgrid=False)
                )
                st.plotly_chart(fig_idx, use_container_width=True)

    # ============================================================
    # 4. БУДУЩИЕ ДИВИДЕНДЫ
    # ============================================================
    st.markdown("### Будущие дивиденды")
    future_div_list = state.g("future_div_list", [])
    
    # Запасной вариант, если вдруг список пуст, но словарь есть
    if not future_div_list:
        future_divs_dict = state.g("future_dividends", {})
        if future_divs_dict:
            future_div_list = [
                {"Тикер": k, "Название": "-", "Период": "-", "Дивиденд": v, "Дата закрытия": "-", "Выплата до": "-"}
                for k, v in future_divs_dict.items()
            ]
            
    if not future_div_list:
        st.info("Нет данных о будущих дивидендах. Загрузите файл Источников с вкладкой «Дивиденды».")
    else:
        div_rows = []
        for d in future_div_list:
            t = d["Тикер"]
            div_amt = d["Дивиденд"]
            
            inst = get_instrument(t, df_stocks)
            market_price = inst.price if inst.price > 0 else 0.0
            yield_market = (div_amt / market_price * 100) if market_price > 0 else 0.0
            
            in_port = next((p for p in positions if p["Тикер"] == t), None)
            port_yield = 0.0
            if in_port:
                tvh = float(in_port["ТВХ"])
                if tvh > 0:
                    port_yield = (div_amt / tvh * 100)
                    
            div_rows.append({
                "Название": d["Название"],
                "Тикер": t,
                "Период": d["Период"],
                "Дивиденд, ₽": div_amt,
                "Дата закрытия": d["Дата закрытия"],
                "Выплата до": d["Выплата до"],
                "Доходность по рынку, %": yield_market,
                "Доходность портфеля, %": port_yield if in_port else "—"
            })
            
        df_divs = pd.DataFrame(div_rows)
        # Сортировка по дате закрытия (по возможности)
        try:
            df_divs["_sort_date"] = pd.to_datetime(df_divs["Дата закрытия"], format="%d.%m.%Y", errors="coerce")
            df_divs = df_divs.sort_values("_sort_date").drop(columns=["_sort_date"])
        except:
            pass
            
        st.dataframe(
            df_divs.style.format({
                "Дивиденд, ₽": "{:.2f}",
                "Доходность по рынку, %": "{:.2f}%",
                "Доходность портфеля, %": lambda x: f"{x:.2f}%" if isinstance(x, float) else x
            }),
            use_container_width=True,
            hide_index=True
        )
