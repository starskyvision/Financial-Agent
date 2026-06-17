"""
将 Kaggle Financial Risk Early Warning Dataset 加载到 RAG 知识库。

数据来源: https://www.kaggle.com/datasets/ziya07/financial-risk-early-warning-dataset
格式: 表格 → 每行转文本描述 → BGE-M3 向量化 → PostgreSQL pgvector

用法:
    python scripts/ingest_financial_risk_dataset.py [--limit 5000] [--batch-size 100]
"""
import os
import sys
import argparse
import asyncio
import structlog

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logger = structlog.get_logger()

ROW_TO_TEXT_TEMPLATE = (
    "公司 {firm_id} 在 {fiscal_year} 财年，所属行业 {industry}，市场环境 {market}。"
    "流动性指标：流动比率 {current_ratio}，速动比率 {quick_ratio}，现金流比率 {cash_flow_ratio}。"
    "盈利能力：ROA {roa}，ROE {roe}，净利率 {net_profit_margin}。"
    "杠杆与偿付能力：产权比率 {debt_to_equity}，资产负债率 {debt_ratio}，利息覆盖倍数 {interest_coverage}。"
    "运营效率：资产周转率 {asset_turnover}，存货周转率 {inventory_turnover}，应收账款周转率 {receivables_turnover}。"
    "成长性：营收增长率 {revenue_growth}，盈利增长率 {earnings_growth}，现金流增长率 {cashflow_growth}。"
    "市场与风险：股价波动率 {stock_volatility}，市场回报率 {market_return}，信用风险指数 {credit_risk_index}。"
    "综合评估：金融风险评分 {risk_score}，风险等级 {risk_category}。"
)


def row_to_text(row) -> str:
    """将 DataFrame 行转为自然语言文本描述。"""
    def val(col, fmt=".4f"):
        v = row.get(col)
        if v is None or (isinstance(v, float) and (v != v)):  # NaN check
            return "N/A"
        if isinstance(v, float):
            return f"{v:{fmt}}"
        return str(v)

    return ROW_TO_TEXT_TEMPLATE.format(
        firm_id=val("Firm_ID", ""),
        fiscal_year=val("Fiscal_Year", ""),
        industry=val("Industry_Type", ""),
        market=val("Market_Condition", ""),
        current_ratio=val("Current_Ratio"),
        quick_ratio=val("Quick_Ratio"),
        cash_flow_ratio=val("Cash_Flow_Ratio"),
        roa=val("ROA"),
        roe=val("ROE"),
        net_profit_margin=val("Net_Profit_Margin"),
        debt_to_equity=val("Debt_to_Equity"),
        debt_ratio=val("Debt_Ratio"),
        interest_coverage=val("Interest_Coverage"),
        asset_turnover=val("Asset_Turnover"),
        inventory_turnover=val("Inventory_Turnover"),
        receivables_turnover=val("Receivables_Turnover"),
        revenue_growth=val("Revenue_Growth"),
        earnings_growth=val("Earnings_Growth"),
        cashflow_growth=val("Cashflow_Growth"),
        stock_volatility=val("Stock_Volatility"),
        market_return=val("Market_Return"),
        credit_risk_index=val("Credit_Risk_Index"),
        risk_score=val("Financial_Risk_Score"),
        risk_category=val("Risk_Category", ""),
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5000, help="最大导入行数")
    parser.add_argument("--batch-size", type=int, default=100, help="每批向量化数量")
    parser.add_argument("--csv", type=str, default="", help="CSV 文件路径（跳过下载）")
    args = parser.parse_args()

    # 1. 加载数据
    csv_path = args.csv
    if not csv_path:
        print("正在下载数据集...")
        import kagglehub
        csv_path = kagglehub.dataset_download("ziya07/financial-risk-early-warning-dataset")
        # kagglehub 返回目录路径，找到 CSV 文件
        import glob
        csv_files = glob.glob(os.path.join(csv_path, "*.csv"))
        if not csv_files:
            print(f"下载目录中未找到 CSV: {csv_path}")
            sys.exit(1)
        csv_path = csv_files[0]
        print(f"下载完成: {csv_path}")

    import pandas as pd
    df = pd.read_csv(csv_path)
    print(f"数据集: {len(df)} 行, {len(df.columns)} 列")
    print(f"列名: {list(df.columns)}")

    if args.limit and len(df) > args.limit:
        df = df.sample(n=args.limit, random_state=42)
        print(f"采样: {args.limit} 行")

    # 2. 转换每行为文本
    print("转换表格行为文本描述...")
    texts = []
    metadatas = []
    for _, row in df.iterrows():
        text = row_to_text(row)
        texts.append(text)
        metadatas.append({
            "company_code": str(row.get("Firm_ID", "")),
            "doc_type": "risk_assessment",
            "doc_title": f"Firm_{row.get('Firm_ID', '')}_{row.get('Fiscal_Year', '')}",
            "content_zh": f"行业: {row.get('Industry_Type', '')}, "
                          f"风险等级: {row.get('Risk_Category', '')}, "
                          f"风险评分: {row.get('Financial_Risk_Score', '')}",
        })

    print(f"生成 {len(texts)} 条文本记录")
    print(f"示例文本（前 200 字）:\n{texts[0][:200]}...")

    # 3. 向量化 + 入库
    print("初始化 embedding 模型...")
    from services.rag.embedder import Embedder
    embedder = Embedder()

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://financial_agent:financial_agent_2024@localhost:15432/financial_agent",
    )
    sync_url = DATABASE_URL.replace("+asyncpg", "")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 批量向量化（一次性 embed 全部，大幅提速）
    print(f"向量化 {len(texts)} 条文本...")
    all_embeddings = embedder.embed(texts)

    # 逐条入库
    from db.models import Document
    from sqlalchemy import text as sa_text
    total = 0
    async with async_session() as session:
        for i, (text, emb, meta) in enumerate(zip(texts, all_embeddings, metadatas)):
            doc = Document(
                company_code=meta["company_code"],
                doc_type=meta["doc_type"],
                doc_title=meta["doc_title"],
                chunk_index=0,
                content=text,
                content_zh=meta["content_zh"],
                embedding=list(emb),
            )
            session.add(doc)
            if (i + 1) % 200 == 0:
                await session.flush()
                print(f"  已写入 {i + 1}/{len(texts)}")
        await session.commit()
        # 统计实际入库数
        result = await session.execute(sa_text("SELECT count(*) FROM documents"))
        total = result.scalar()

    print(f"\n入库完成! 总计 {len(texts)} 行 → {total} chunks")

    await engine.dispose()
    print(f"\n入库完成! 总计 {len(texts)} 行 → {total} chunks")


if __name__ == "__main__":
    asyncio.run(main())
