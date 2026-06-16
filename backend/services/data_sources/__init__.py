from services.data_sources.base import DataSourceAdapter, DataSourceConfig
from services.data_sources.akshare_adapter import AKShareAdapter

_instances: dict[str, DataSourceAdapter] = {}


def create_data_source(config: DataSourceConfig) -> DataSourceAdapter:
    """创建或复用数据源实例"""
    key = config.source_type
    if key in _instances:
        return _instances[key]

    match config.source_type:
        case "akshare":
            adapter = AKShareAdapter(config)
        case "tushare":
            raise NotImplementedError("Tushare adapter not yet implemented")
        case "wind":
            raise NotImplementedError("Wind adapter not yet implemented")
        case _:
            raise ValueError(f"Unsupported data source: {config.source_type}")

    _instances[key] = adapter
    return adapter


def clear_cache():
    """清理缓存的适配器实例（测试用）"""
    _instances.clear()
