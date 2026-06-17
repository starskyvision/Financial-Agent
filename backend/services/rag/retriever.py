import structlog
from sqlalchemy import text
from services.rag.embedder import Embedder
from services.rag.config import RAGConfig

logger = structlog.get_logger()


class Retriever:
    """pgvector 语义检索封装。"""

    def __init__(self, session_factory, embedder: Embedder | None = None):
        self.session_factory = session_factory
        self.embedder = embedder or Embedder()
        self.top_k = RAGConfig.top_k

    async def search(
        self, query: str, company_code: str = "",
        doc_type: str = "", top_k: int | None = None,
    ) -> list[dict]:
        """语义检索文档切片。pgvector 不可用时返回空列表。"""
        k = top_k or self.top_k
        query_vec = self.embedder.embed_query(query)

        conditions = ["embedding IS NOT NULL"]
        params = {"query_vec": query_vec, "k": k}

        if company_code:
            conditions.append("company_code = :company_code")
            params["company_code"] = company_code
        if doc_type:
            conditions.append("doc_type = :doc_type")
            params["doc_type"] = doc_type

        where_clause = " AND ".join(conditions)

        sql = text(f"""
            SELECT id, company_code, doc_type, doc_title, content, content_zh,
                   1 - (embedding <=> :query_vec) AS score
            FROM documents
            WHERE {where_clause}
            ORDER BY embedding <=> :query_vec
            LIMIT :k
        """)

        try:
            async with self.session_factory() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
        except Exception as e:
            logger.warning("retriever_search_failed", error=str(e))
            return []

        return [
            {
                "id": row.id,
                "company_code": row.company_code,
                "doc_type": row.doc_type,
                "doc_title": row.doc_title or "",
                "content": row.content,
                "content_zh": row.content_zh or "",
                "score": round(float(row.score), 4),
            }
            for row in rows
        ]
