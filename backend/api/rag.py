"""
RAG 知识库 API — 投研报告上传、检索、管理

POST   /api/v1/rag/upload      上传 PDF 投研报告 → 向量化入库
GET    /api/v1/rag/search       语义检索
GET    /api/v1/rag/documents    列出已入库文档
DELETE /api/v1/rag/documents/{id} 删除文档
"""
import os
import structlog
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/rag", tags=["RAG"])


class UploadResponse(BaseModel):
    doc_id: int
    chunks: int
    doc_title: str
    company_code: str


class SearchResult(BaseModel):
    id: int
    doc_title: str
    company_code: str
    doc_type: str
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class DocumentItem(BaseModel):
    id: int
    doc_title: str
    company_code: str
    doc_type: str
    chunks: int
    created_at: str


class DocListResponse(BaseModel):
    total: int
    documents: list[DocumentItem]


# --- 数据库会话工厂 ---
def _get_session_factory():
    """创建异步数据库会话工厂。"""
    import os as _os
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    db_url = _os.getenv(
        "DATABASE_URL",
        "postgresql://financial_agent:financial_agent_2024@localhost:15432/financial_agent",
    )
    if "asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# --- PDF 文本提取 ---
def extract_pdf_text(file_bytes: bytes) -> str:
    """从 PDF 字节流中提取文本。"""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text_parts = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            text_parts.append(text.strip())
    doc.close()
    return "\n\n".join(text_parts)


@router.post("/upload", response_model=UploadResponse)
async def upload_report(
    file: UploadFile = File(...),
    company_code: str = Form(default=""),
    doc_title: str = Form(default=""),
):
    """上传 PDF 投研报告：提取文本 → 切块 → 向量化 → 入库。"""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    title = doc_title or file.filename.replace(".pdf", "")
    code = company_code or "unknown"

    try:
        file_bytes = await file.read()
        text = extract_pdf_text(file_bytes)

        if not text or len(text) < 50:
            raise HTTPException(status_code=400, detail="PDF 文本内容不足（< 50 字）")

        logger.info("rag_upload_pdf", title=title, code=code, text_len=len(text))

        # 入库
        from services.rag.ingester import Ingester
        session_factory = _get_session_factory()
        ingester = Ingester(session_factory)
        chunk_ids = await ingester.index_document(
            content=text,
            company_code=code,
            doc_type="report",
            doc_title=title,
            content_zh=f"投研报告: {title}",
        )

        logger.info("rag_upload_done", title=title, chunks=len(chunk_ids))
        return UploadResponse(
            doc_id=chunk_ids[0] if chunk_ids else 0,
            chunks=len(chunk_ids),
            doc_title=title,
            company_code=code,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rag_upload_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"入库失败: {str(e)}")


@router.get("/search", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., description="搜索关键词"),
    company_code: str = Query(default="", description="按股票代码过滤"),
    top_k: int = Query(default=5, ge=1, le=20),
):
    """语义检索知识库——基于 BGE-M3 向量相似度。"""
    from services.rag.search import search_rag
    session_factory = _get_session_factory()

    results = await search_rag(q, company_code=company_code, top_k=top_k, session_factory=session_factory)

    items = [
        SearchResult(
            id=r["id"],
            doc_title=r.get("doc_title", ""),
            company_code=r.get("company_code", ""),
            doc_type=r.get("doc_type", ""),
            content=r["content"][:200],
            score=r["score"],
        )
        for r in results
    ]
    return SearchResponse(query=q, results=items)


@router.get("/documents", response_model=DocListResponse)
async def list_documents(
    company_code: str = Query(default="", description="按股票代码过滤"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """列出已入库的文档（去重，按标题聚合）。"""
    from sqlalchemy import text
    session_factory = _get_session_factory()

    sql = text("""
        SELECT doc_title, company_code, doc_type,
               count(*) AS chunks, min(created_at) AS created_at
        FROM documents
        WHERE (:code = '' OR company_code = :code)
        GROUP BY doc_title, company_code, doc_type
        ORDER BY min(created_at) DESC
        LIMIT :limit
    """)

    async with session_factory() as session:
        result = await session.execute(sql, {"code": company_code, "limit": limit})
        rows = result.fetchall()

    docs = [
        DocumentItem(
            id=i,
            doc_title=row.doc_title or f"doc_{i}",
            company_code=row.company_code,
            doc_type=row.doc_type,
            chunks=row.chunks,
            created_at=str(row.created_at),
        )
        for i, row in enumerate(rows)
    ]
    return DocListResponse(total=len(docs), documents=docs)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: int):
    """删除指定 ID 的文档切片。"""
    from sqlalchemy import text
    session_factory = _get_session_factory()

    async with session_factory() as session:
        result = await session.execute(
            text("DELETE FROM documents WHERE id = :id"), {"id": doc_id}
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="文档不存在")

    logger.info("rag_doc_deleted", doc_id=doc_id)
    return {"deleted": True, "doc_id": doc_id}
