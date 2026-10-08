"""出差申请工作流的 Prompt 模板（纯字符串，零逻辑）。"""

TRIP_EXTRACT_PROMPT = """从用户的差旅需求中提取信息。

可提取字段：
- trip_reason: 出差事由（拜访客户/参加会议/项目驻场等，简短描述）
- departure_city: 出发城市
- arrival_city: 目的地城市
- departure_date: 出发日期（YYYY-MM-DD）
- return_date: 返程日期（YYYY-MM-DD，未提及则留空字符串）

规则：
1. 只提取用户明确提到的信息，不要臆造。
2. 相对日期（如"下周一""三天"）请基于今天是 {today} 推算为具体日期。
3. 未提及的字段留空字符串。

用户输入：{input}
"""

PLAN_SUMMARY_PROMPT = """根据以下信息，生成一份简洁的《差旅申请单》草稿：

出差事由：{reason}
行程：{departure_city} → {arrival_city}，{departure_date} 出发{return_suffix}
目的地天气：{weather}
推荐车次：{trains}
推荐酒店：{hotels}

要求：
1. 分三节：一、出差事由；二、行程安排；三、出行建议（结合天气给一句提醒）。
2. 车次/酒店信息如实引用，不要编造。
3. Markdown 格式，语言简洁专业。
"""
