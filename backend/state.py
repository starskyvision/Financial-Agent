"""
AgentState 与核心类型定义

金融多智能体协作系统中所有 LangGraph 节点之间传递的数据结构。
Pydantic 模型确保序列化兼容性（JSON -> Redis/MySQL）。
"""

from typing import TypedDict
from pydantic import BaseModel


class IntentResult(BaseModel):
    """意图分类器输出"""
    intent: str
    company_code: str
    company_name: str = ""
    company_name_en: str = ""  # English name for cross-language RAG retrieval
    report_date: str = ""
    metric_names: list[str] = []
    query_type: str = ""
    query_target: str = ""  # e.g. "gold", "USD/CNY", "crude oil"


class DupontResult(BaseModel):
    """杜邦分解计算结果"""
    roe: float
    net_margin: float
    asset_turnover: float
    equity_multiplier: float
    is_valid: bool
    missing_metrics: list[str] = []


class Anomaly(BaseModel):
    """异动检测结果"""
    metric_name: str
    current_value: float
    yoy_value: float | None = None
    change_pct: float | None = None
    severity: str  # warning | critical


class SentimentDetail(BaseModel):
    """单条新闻情感"""
    title: str
    sentiment: str   # positive | neutral | negative
    score: float     # 0~1
    reasoning: str = ""


class SentimentResult(BaseModel):
    """舆情分析结果"""
    overall_sentiment: str  # positive | neutral | negative
    overall_score: float
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    key_topics: list = []  # list[str] (旧) 或 list[dict] (新: {"topic":"","description":""})
    summary: str = ""
    details: list[SentimentDetail] = []


class AgentState(TypedDict, total=False):
    """LangGraph StateGraph 节点间传递的全局状态

    所有字段均为 NotRequired（total=False），
    节点只读写自己关心的字段。
    """
    # 任务元数据
    task_id: str
    intent: str
    query_type: str
    query_target: str

    # 用户输入
    company_code: str
    company_name: str
    company_name_en: str
    report_date: str

    # 各 Agent 输出
    raw_data: dict | None
    financial_analysis: dict | None
    sentiment_result: dict | None

    # 输出
    chat_reply: str | None
    draft_report: str | None

    # 反思控制
    errors: list[str]
    prev_fact_errors: list[str]
    retry_count: int
    status: str  # pending | running | done | failed


def make_initial_state(task_id: str, company_code: str = "", report_date: str = "") -> AgentState:
    """创建一个干净的初始 AgentState，用于 LangGraph 图启动。"""
    return AgentState(
        task_id=task_id,
        intent="",
        company_code=company_code,
        company_name="",
        company_name_en="",
        report_date=report_date,
        raw_data=None,
        financial_analysis=None,
        sentiment_result=None,
        chat_reply=None,
        draft_report=None,
        errors=[],
        prev_fact_errors=[],
        retry_count=0,
        status="pending",
    )
