from services.env import env_int, env_str


class RAGConfig:
    chunk_size: int = env_int("RAG_CHUNK_SIZE", "500")
    chunk_overlap: int = env_int("RAG_CHUNK_OVERLAP", "50")
    top_k: int = env_int("RAG_TOP_K", "5")
    embedding_dim: int = env_int("EMBEDDING_DIM", "1024")
    model_path: str = env_str("BGE_M3_PATH", "./models/bge-m3")

    # NOTE: embedding_dim is a target/expected dimension, primarily for
    # documentation and startup validation.  The actual embedding dimension
    # is determined by the SentenceTransformer model at runtime.
    # See Embedder.__init__() for startup validation against this value.
