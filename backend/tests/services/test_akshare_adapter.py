import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.data_sources.base import DataSourceConfig
from services.data_sources.akshare_adapter import AKShareAdapter, normalize_stock_code
from services.data_sources import create_data_source, clear_cache


class TestNormalizeStockCode:
    def test_pure_number(self):
        assert normalize_stock_code("600519") == "600519"

    def test_with_sh_suffix(self):
        assert normalize_stock_code("600519.SH") == "600519"

    def test_with_sz_suffix(self):
        assert normalize_stock_code("000001.SZ") == "000001"

    def test_with_sh_prefix(self):
        assert normalize_stock_code("SH600519") == "600519"


class TestAKShareAdapter:
    @pytest.fixture
    def adapter(self):
        config = DataSourceConfig(source_type="akshare", timeout=10)
        return AKShareAdapter(config)

    @pytest.mark.asyncio
    async def test_fetch_financials_returns_dict(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_financial_abstract_ths") as mock_ak:
            import pandas as pd
            mock_df = pd.DataFrame({"净资产收益率": [0.15, 0.14], "营业收入": [100e8, 90e8]})
            mock_ak.return_value = mock_df

            result = await adapter.fetch_financials("600519", "2024-09-30", ["roe", "revenue"])
            assert isinstance(result, dict)
            assert "roe" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_financials_empty_on_error(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_financial_abstract_ths",
                   side_effect=Exception("network error")):
            result = await adapter.fetch_financials("600519", "2024-09-30", ["roe"])
            assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_news_returns_list(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_news_em") as mock_ak:
            import pandas as pd
            mock_df = pd.DataFrame({"标题": ["茅台Q3业绩增长"], "内容": ["贵州茅台第三季度营收..."],
                                     "发布时间": ["2024-10-28"]})
            mock_ak.return_value = mock_df

            result = await adapter.fetch_news("600519", 30)
            assert isinstance(result, list)
            if result:
                assert "title" in result[0]

    @pytest.mark.asyncio
    async def test_fetch_news_empty_on_error(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_news_em",
                   side_effect=Exception("network error")):
            result = await adapter.fetch_news("600519", 30)
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_documents_returns_empty(self, adapter):
        result = await adapter.fetch_documents("600519", "announcement", 5)
        assert result == []


class TestCreateDataSource:
    def setup_method(self):
        clear_cache()

    def test_create_akshare(self):
        config = DataSourceConfig(source_type="akshare")
        adapter = create_data_source(config)
        from services.data_sources.akshare_adapter import AKShareAdapter
        assert isinstance(adapter, AKShareAdapter)

    def test_create_unsupported_raises(self):
        config = DataSourceConfig(source_type="wind")
        with pytest.raises(NotImplementedError):
            create_data_source(config)

    def test_singleton_cache(self):
        config = DataSourceConfig(source_type="akshare")
        a1 = create_data_source(config)
        a2 = create_data_source(config)
        assert a1 is a2
