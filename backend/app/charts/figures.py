import json

import plotly.graph_objects as go


def build_charts(curve, trades, lots=None, price_label="收盘价"):
    lots = lots or []
    dates = curve["date"].astype(str).tolist()

    equity = go.Figure()
    equity.add_scatter(x=dates, y=curve["equity"], name="账户权益", line={"color": "#2563eb", "width": 2})
    if "cash" in curve:
        equity.add_scatter(x=dates, y=curve["cash"], name="现金", line={"color": "#16a34a"})
    if "market_value" in curve:
        equity.add_scatter(x=dates, y=curve["market_value"], name="持仓市值", line={"color": "#f59e0b"})
    equity.update_layout(title="账户权益、现金与持仓市值", template="plotly_white", yaxis_title="金额（元）", hovermode="x unified")

    price = go.Figure()
    price.add_scatter(x=dates, y=curve["price"], name=price_label, line={"color": "#334155", "width": 2})
    price.add_scatter(x=dates, y=curve["ma"], name="MA", line={"color": "#f59e0b"})
    if "next_grid_price" in curve:
        price.add_scatter(x=dates, y=curve["next_grid_price"], name="下一补仓价格", line={"color": "#8b5cf6", "dash": "dot"})

    filled = [t for t in trades if t.status == "FILLED"]
    marker_groups = [
        ("首仓", [t for t in filled if t.side == "BUY" and t.layer_no == 0], "#16a34a", "triangle-up"),
        ("补仓", [t for t in filled if t.side == "BUY" and (t.layer_no or 0) > 0], "#059669", "diamond"),
        ("Lot 止盈", [t for t in filled if t.side == "SELL" and t.reason.startswith("Lot")], "#dc2626", "triangle-down"),
        ("组合清仓", [t for t in filled if t.side == "SELL" and t.reason.startswith("组合")], "#7c3aed", "x"),
    ]
    for name, group, color, symbol in marker_groups:
        if group:
            price.add_scatter(
                x=[str(t.date) for t in group], y=[t.price for t in group], mode="markers", name=name,
                text=[t.reason for t in group], hovertemplate="%{x}<br>%{y:.4f}<br>%{text}<extra></extra>",
                marker={"color": color, "symbol": symbol, "size": 11},
            )
    end_date = dates[-1]
    for lot in lots:
        price.add_scatter(
            x=[str(lot.buy_date), str(lot.sell_date) if lot.sell_date else end_date],
            y=[lot.buy_price, lot.buy_price], mode="lines", name=f"{lot.lot_id} 成本线",
            line={"width": 1, "dash": "dash"}, opacity=0.55, legendgroup="lot-costs",
            showlegend=True,
        )
    price.update_layout(title="价格、MA、逐层成本与交易标记", template="plotly_white", hovermode="x unified")

    drawdown = go.Figure(go.Scatter(
        x=dates, y=curve["drawdown"], fill="tozeroy", name="回撤", line={"color": "#dc2626"}
    ))
    drawdown.update_layout(title="账户回撤曲线", template="plotly_white", yaxis_tickformat=".1%", hovermode="x unified")
    return {
        "equity": json.loads(equity.to_json()),
        "price": json.loads(price.to_json()),
        "drawdown": json.loads(drawdown.to_json()),
    }
