from state import DupontResult


def compute_dupont(metrics: dict) -> DupontResult:
    """杜邦分解: ROE = 净利率 × 资产周转率 × 权益乘数"""
    required = ["net_profit", "revenue", "total_assets"]
    missing = [m for m in required if m not in metrics or metrics[m] is None or metrics[m] == 0]

    if missing:
        return DupontResult(
            roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
            is_valid=False, missing_metrics=missing,
        )

    net_profit = metrics.get("net_profit", 0)
    revenue = metrics.get("revenue", 0)
    total_assets = metrics.get("total_assets", 0)
    total_liabilities = metrics.get("total_liabilities", 0)
    equity = total_assets - total_liabilities

    if revenue == 0 or total_assets == 0 or equity == 0:
        return DupontResult(
            roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
            is_valid=False, missing_metrics=["equity_data"],
        )

    net_margin = round(net_profit / revenue, 4)
    asset_turnover = round(revenue / total_assets, 4)
    equity_multiplier = round(total_assets / equity, 4)
    roe = round(net_margin * asset_turnover * equity_multiplier, 4)

    return DupontResult(
        roe=roe, net_margin=net_margin, asset_turnover=asset_turnover,
        equity_multiplier=equity_multiplier, is_valid=True,
    )
