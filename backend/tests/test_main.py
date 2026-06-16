import pytest
from httpx import AsyncClient, ASGITransport
from main import app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"


class TestTaskEndpoint:
    @pytest.mark.asyncio
    async def test_submit_task_requires_code(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/tasks", json={})
            assert response.status_code == 422


class TestReportEndpoint:
    @pytest.mark.asyncio
    async def test_report_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/reports/nonexistent")
            assert response.status_code == 404
