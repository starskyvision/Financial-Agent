import os


class RAGConfig:
    chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "500"))
    chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
    top_k: int = int(os.getenv("RAG_TOP_K", "5"))
    embedding_dim: int = 1024
    model_path: str = os.getenv("BGE_M3_PATH", "/models/bge-m3")
