"""酒店查询数据源（Mock）。

接口契约：hotel_search(city, checkin_date) -> list[dict]
酒店字典字段：name / price / rating / distance / breakfast
"""

from __future__ import annotations

from backend.config import get_settings
from backend.core.exceptions import DataSourceError


async def hotel_search(city: str, checkin_date: str) -> list[dict]:
    """查询目的地城市酒店（Mock：返回固定结构推荐列表）。"""
    s = get_settings()
    if s.hotel_provider == "mock":
        return [
            {"name": f"{city}商务亚朵酒店", "price": 428, "rating": 4.8,
             "distance": "距市中心 0.8km", "breakfast": "含双早"},
            {"name": f"{city}中心智选假日酒店", "price": 358, "rating": 4.6,
             "distance": "距市中心 1.2km", "breakfast": "含双早"},
            {"name": f"{city}如家精选酒店", "price": 268, "rating": 4.3,
             "distance": "距市中心 2.5km", "breakfast": "不含早"},
        ]
    raise DataSourceError(f"未实现的酒店数据源: {s.hotel_provider!r}")
