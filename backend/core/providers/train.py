"""12306 票务查询数据源。

【硬约束】禁用爬虫（见架构方案.md 已确认决策）：
- 开发期：本文件 Mock 实现，返回固定 JSON 结构假数据，先跑通流程
- 生产期：接第三方聚合 API（携程企业版 / 去哪儿 / RapidAPI 候选），在
  train_search 里按 settings.train_provider 分派即可，Agent 代码零改动

接口契约：train_search(departure, arrival, date) -> list[dict]
车次字典字段：train_no / departure / arrive / duration / price_second / price_first / seats_left
"""

from __future__ import annotations

from backend.config import get_settings
from backend.core.exceptions import DataSourceError

_MOCK_TRAINS = [
    # (车次, 出发时刻, 到达时刻, 历时, 二等座, 一等座, 余票)
    ("G31", "08:00", "12:36", "4小时36分", "¥553", "¥933", 32),
    ("G137", "10:15", "14:52", "4小时37分", "¥553", "¥933", 15),
    ("D321", "13:05", "18:40", "5小时35分", "¥328", "¥525", 58),
]


async def train_search(departure: str, arrival: str, date: str) -> list[dict]:
    """查询某日出发站 → 到达站的车次（余票/票价）。

    Mock：返回固定 JSON 结构；thirdparty：后续接第三方聚合 API。
    失败时抛 DataSourceError，由调用方（agent 节点）静默降级。
    """
    s = get_settings()
    if s.train_provider == "mock":
        return [
            {
                "train_no": no,
                "departure": dep_time,
                "arrive": arr_time,
                "duration": duration,
                "price_second": price2,
                "price_first": price1,
                "seats_left": seats,
            }
            for no, dep_time, arr_time, duration, price2, price1, seats in _MOCK_TRAINS
        ]
    # 生产期：在这里实现第三方聚合 API 调用（禁用爬虫）
    raise DataSourceError(f"未实现的票务数据源: {s.train_provider!r}")
