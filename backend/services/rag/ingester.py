import structlog
from sqlalchemy import delete
from services.rag.chunker import chunk_text
from services.rag.embedder import Embedder
from services.rag.config import RAGConfig
from db.models import Document

logger = structlog.get_logger()


class Ingester:
    """文档入库管道：切块 → 向量化 → 写入 documents 表。"""

    def __init__(self, session_factory, embedder: Embedder | None = None):
        self.session_factory = session_factory
        self.embedder = embedder or Embedder()
        self.chunk_size = RAGConfig.chunk_size
        self.chunk_overlap = RAGConfig.chunk_overlap

    async def index_document(
        self, content: str, company_code: str, doc_type: str,
        doc_title: str = "", content_zh: str = "",
    ) -> list[int]:
        """单篇文档入库。返回 chunk ID 列表。pgvector 不可用时跳过 embedding。"""
        chunks = chunk_text(content, self.chunk_size, self.chunk_overlap)
        if not chunks:
            return []

        # Try to generate embeddings; skip if pgvector unavailable
        try:
            embeddings = self.embedder.embed(chunks)
        except Exception as e:
            logger.warning("embedding_failed", error=str(e))
            embeddings = [None] * len(chunks)

        chunk_ids = []
        async with self.session_factory() as session:
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                doc = Document(
                    company_code=company_code,
                    doc_type=doc_type,
                    doc_title=doc_title,
                    chunk_index=i,
                    content=chunk,
                    content_zh=content_zh if i == 0 else "",
                    embedding=emb if emb else None,
                )
                session.add(doc)
                await session.flush()
                chunk_ids.append(doc.id)
            await session.commit()

        logger.info("document_indexed", title=doc_title, chunks=len(chunks),
                     company=company_code)
        return chunk_ids

    async def index_batch(self, documents: list[dict]) -> int:
        """批量入库。"""
        total = 0
        for doc in documents:
            ids = await self.index_document(
                content=doc["content"],
                company_code=doc.get("company_code", ""),
                doc_type=doc.get("doc_type", "report"),
                doc_title=doc.get("doc_title", ""),
                content_zh=doc.get("content_zh", ""),
            )
            total += len(ids)
        return total

    async def delete_by_company(self, company_code: str) -> int:
        """删除某公司所有切片。"""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(Document).where(Document.company_code == company_code)
            )
            await session.commit()
            count = result.rowcount
            logger.info("documents_deleted", company=company_code, count=count)
            return count
