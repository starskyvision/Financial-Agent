from services.rag.chunker import chunk_text


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = "这是一段简短的研报内容。"
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_into_chunks(self):
        text = "测试内容。" * 200
        chunks = chunk_text(text, chunk_size=200, overlap=30)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 230

    def test_overlap_preserves_context(self):
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        chunks = chunk_text(text, chunk_size=10, overlap=3)
        assert len(chunks) > 1
        assert chunks[1][:3] == chunks[0][-3:]

    def test_empty_text_returns_empty(self):
        assert chunk_text("", chunk_size=500, overlap=50) == []
        assert chunk_text("   ", chunk_size=500, overlap=50) == []

    def test_paragraph_boundary_chunking(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1

    def test_very_long_text_produces_multiple_chunks(self):
        text = "A" * 2000
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 3
        for c in chunks:
            assert len(c) <= 500
