# Lazy imports: avoid eagerly loading torch/SentenceTransformer at module import time.
# This allows tests and other modules to import from services.rag without GPU/Model deps.

def __getattr__(name: str):
    if name == "Embedder":
        from services.rag.embedder import Embedder
        return Embedder
    elif name == "chunk_text":
        from services.rag.chunker import chunk_text
        return chunk_text
    elif name == "Retriever":
        from services.rag.retriever import Retriever
        return Retriever
    elif name == "Ingester":
        from services.rag.ingester import Ingester
        return Ingester
    elif name == "search_rag":
        from services.rag.search import search_rag
        return search_rag
    elif name == "RAGConfig":
        from services.rag.config import RAGConfig
        return RAGConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Embedder", "chunk_text", "Retriever", "Ingester", "search_rag", "RAGConfig"]
