import os
from fastapi.testclient import TestClient


class TestE2EHealthCheck:
    def test_health_returns_all_services(self):
        os.environ["API_KEY"] = ""
        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "postgres" in data
        assert "redis" in data
        assert "version" in data


class TestE2EChatSSE:
    def test_chat_streams_sse(self):
        os.environ["API_KEY"] = ""
        from main import app
        client = TestClient(app)
        resp = client.post(
            "/api/v1/chat",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type


class TestE2ETaskLifecycle:
    def test_submit_and_query_task(self):
        os.environ["API_KEY"] = ""
        from main import app
        client = TestClient(app)
        resp = client.post("/api/v1/tasks", json={
            "company_code": "600519",
            "report_date": "2024-09-30",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        task_id = data["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200


class TestE2EAuthFlow:
    def test_public_endpoints_no_auth(self):
        os.environ["API_KEY"] = "secret"
        import sys
        for k in list(sys.modules.keys()):
            if k.startswith("main") or k.startswith("middleware"):
                del sys.modules[k]
        from main import app
        client = TestClient(app)
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/docs").status_code == 200

    def test_protected_endpoint_rejects(self):
        os.environ["API_KEY"] = "secret"
        import sys
        for k in list(sys.modules.keys()):
            if k.startswith("main") or k.startswith("middleware"):
                del sys.modules[k]
        from main import app
        client = TestClient(app)
        resp = client.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code == 401

    def test_valid_key_passes(self):
        os.environ["API_KEY"] = "secret"
        import sys
        for k in list(sys.modules.keys()):
            if k.startswith("main") or k.startswith("middleware"):
                del sys.modules[k]
        from main import app
        client = TestClient(app)
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-API-Key": "secret"},
        )
        assert resp.status_code != 401


class TestE2ERAGPipeline:
    def test_rag_search_without_db_returns_empty(self):
        import asyncio

        async def run():
            from services.rag.search import search_rag
            return await search_rag("测试查询", company_code="600519", session_factory=None)

        results = asyncio.run(run())
        assert results == []

    def test_chunker_with_real_text(self):
        from services.rag.chunker import chunk_text
        text = "这是一段测试研报内容。" * 50
        chunks = chunk_text(text, chunk_size=200, overlap=30)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) > 0
            assert len(c) <= 230
