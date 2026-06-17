"""对 report_generator_node 暴露的简化检索接口。"""
import structlog
from services.rag.retriever import Retriever
from services.rag.embedder import Embedder

logger = structlog.get_logger()

_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


async def search_rag(
    query: str, company_code: str = "", top_k: int = 5,
    session_factory=None,
) -> list[dict]:
    """从知识库中语义检索相关文档切片。session_factory=None 时返回空列表。"""
    if session_factory is None:
        logger.warning("rag_search_skip_no_session")
        return []

    try:
        embedder = _get_embedder()
        retriever = Retriever(session_factory, embedder=embedder)
        results = await retriever.search(
            query, company_code=company_code, top_k=top_k,
        )
        logger.info("rag_search_done", query=query[:50], results=len(results))
        return results
    except Exception as e:
        logger.error("rag_search_error", error=str(e))
        return []
