import structlog
from sentence_transformers import SentenceTransformer
from services.rag.config import RAGConfig

logger = structlog.get_logger()


class Embedder:
    """BGE-M3 本地 embedding 模型封装。"""

    def __init__(self, model_path: str | None = None):
        path = model_path or RAGConfig.model_path
        logger.info("embedder_loading", model_path=path)
        self.model = SentenceTransformer(path)
        self.dim = RAGConfig.embedding_dim
        logger.info("embedder_loaded", dim=self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化，返回归一化的 1024 维向量。"""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """单条查询向量化。"""
        return self.embed([text])[0]
