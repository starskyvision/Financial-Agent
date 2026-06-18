from state import DupontResult
from constants.metrics import ROE_DEVIATION_TOLERANCE


def compute_dupont(metrics: dict) -> DupontResult:
    """杜邦分解: ROE = 净利率 × 资产周转率 × 权益乘数

    支持部分数据——total_assets 缺失时仍可计算净利率和权益乘数。
    """
    net_profit = metrics.get("net_profit")
    revenue = metrics.get("revenue")
    total_assets = metrics.get("total_assets")
    total_liabilities = metrics.get("total_liabilities")
    equity_multiplier = metrics.get("equity_multiplier")
    roe = metrics.get("roe")
    net_margin = None
    asset_turnover = None
    missing = []

    # 1. 净利率 = 净利润 / 营收
    if net_profit and revenue and revenue > 0:
        net_margin = round(net_profit / revenue, 4)
    elif not net_profit or net_profit == 0:
        missing.append("net_profit")
    elif not revenue or revenue == 0:
        missing.append("revenue")

    # 2. 资产周转率 = 营收 / 总资产
    if total_assets and revenue and total_assets > 0 and revenue > 0:
        asset_turnover = round(revenue / total_assets, 4)
    # total_assets 缺失不算错误，AKShare 不提供此字段

    # 3. 权益乘数（优先用已有值，其次从 产权比率 推导，最后从 total_assets/total_liabilities）
    if equity_multiplier is None:
        equity_ratio = metrics.get("equity_ratio")
        if equity_ratio and equity_ratio > 0:
            # 产权比率 = 总负债/净资产，权益乘数 = 总资产/净资产 = 1 + 产权比率
            equity_multiplier = round(1.0 + equity_ratio, 4)
        elif total_assets and total_liabilities and total_assets > 0:
            equity = total_assets - total_liabilities
            if equity > 0:
                equity_multiplier = round(total_assets / equity, 4)
    if equity_multiplier is None:
        equity_multiplier = 0

    # 4. 综合判断有效性
    has_basic = net_margin is not None  # 净利率是最基本的需求
    if not has_basic:
        missing.extend(["net_profit", "revenue"])

    # 5. ROE: 优先使用传入值，其次从三分量计算
    # 关键：当 asset_turnover 为 0（total_assets 缺失）时，不能用三分量推导 ROE
    computed_roe = None
    if net_margin is not None and asset_turnover is not None and asset_turnover > 0 and equity_multiplier and equity_multiplier > 0:
        computed_roe = round(net_margin * asset_turnover * equity_multiplier, 4)

    if roe is None:
        roe = computed_roe  # 可能为 None

    # 6. 一致性校验：传入 ROE 与计算 ROE 偏差 > ROE_DEVIATION_TOLERANCE 时标记
    formula_mismatch = False
    if roe is not None and computed_roe is not None and roe > 0 and computed_roe > 0:
        deviation = abs(roe - computed_roe) / roe
        if deviation > ROE_DEVIATION_TOLERANCE:
            formula_mismatch = True
            missing.append(f"ROE 公式不闭合: 传入 {roe}, 计算 {computed_roe}, 偏差 {deviation:.1%}")

    return DupontResult(
        roe=roe if roe else 0,
        net_margin=net_margin if net_margin else 0,
        asset_turnover=asset_turnover if asset_turnover else 0,
        equity_multiplier=equity_multiplier,
        is_valid=has_basic and len(missing) == 0 and not formula_mismatch,
        missing_metrics=missing,
    )
