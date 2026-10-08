"""天气查询数据源（Mock）。

接口契约：weather_query(city, date) -> dict
字典字段：city / date / weather / temperature / advice
"""

from __future__ import annotations

import hashlib

from backend.config import get_settings
from backend.core.exceptions import DataSourceError

# (天气, 温度区间, 出行建议)
_WEATHER_OPTIONS = [
    ("晴", "12~24℃", "天气晴好，适合出行"),
    ("多云", "10~20℃", "多云天气，出行注意保暖"),
    ("小雨", "8~16℃", "有小雨，请携带雨具"),
]


async def weather_query(city: str, date: str) -> dict:
    """查询某城市某日天气。

    Mock：按 (城市+日期) 取稳定伪随机天气——同一城市同一天结果一致。
    注意不用 hash()（Python 进程级随机盐，结果不稳定），用 md5 保证确定性。
    """
    digest = hashlib.md5(f"{city}|{date}".encode()).hexdigest()
    weather, temp, advice = _WEATHER_OPTIONS[int(digest, 16) % len(_WEATHER_OPTIONS)]
    return {"city": city, "date": date, "weather": weather, "temperature": temp, "advice": advice}
