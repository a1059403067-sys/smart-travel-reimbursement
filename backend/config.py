"""配置中心：全项目唯一配置来源。

设计（参考 EduAgent backend/config.py）：

- 从项目根目录 .env.local 读取（.env.local.txt 为模板留档，真实值不入 Git）
- 密钥类字段不设默认值 + 非空校验：缺失/为空时启动期直接报错，故障提前暴露
- 其余字段全部带默认值，clone 后只需填 DEEPSEEK_API_KEY 即可跑
- @lru_cache 单例 get_settings()，全项目唯一实例

用法：

    from backend.config import get_settings

    settings = get_settings()
    print(settings.database_url)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 容忍 .env 里的多余字段
    )

    # ── 应用基础 ──
    app_name: str = "智能差旅报销系统"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8006
    log_level: str = "INFO"
    default_tenant_id: str = "tenant_default"

    # ── 数据库（本地开发默认值；生产必须改 .env.local）──
    db_host: str = "localhost"
    db_port: int = 5433  # 宿主端口偏移，避开本机 5432（docker-compose 约定）
    db_name: str = "travel_reimbursement"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # ── LLM（DeepSeek，OpenAI 兼容层）──
    deepseek_api_key: str  # 必填，用户在 .env.local 中填写
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_chat: str = "deepseek-chat"     # 主流程模型
    deepseek_model_intent: str = "deepseek-chat"   # 意图路由模型（temperature=0）
    llm_global_concurrency: int = 50   # 全局限流（并发请求数）
    llm_per_user_concurrency: int = 10  # 单用户限流（并发请求数）

    # ── JWT ──
    jwt_secret_key: str  # 必填（已生成随机值写入 .env.local，生产环境请更换）
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 小时

    # ── 外部数据源（P1 起用；train 禁用爬虫，见架构方案.md）──
    train_provider: str = "mock"  # mock | thirdparty
    hotel_provider: str = "mock"  # mock | thirdparty
    map_provider: str = "mock"    # mock | thirdparty

    @field_validator("deepseek_api_key", "jwt_secret_key", mode="after")
    @classmethod
    def _secret_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("必填配置不能为空，请在项目根目录 .env.local 中填写")
        return v

    @model_validator(mode="after")
    def _prod_guards(self):
        """生产环境强校验（审核 R-04）：弱默认凭据直接启动失败。"""
        if self.app_env == "prod":
            if self.db_password == "postgres" or self.db_user == "postgres":
                raise ValueError("生产环境禁止使用默认数据库凭据，请在 .env.local 中修改 DB_USER/DB_PASSWORD")
            if self.jwt_secret_key == self.__class__.model_fields["jwt_secret_key"].default:
                raise ValueError("生产环境必须更换 JWT 密钥")
        return self

    @property
    def database_url(self) -> str:
        """asyncpg 连接串（派生属性，不单独存配置）。"""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """配置单例。"""
    return Settings()


if __name__ == "__main__":
    # 离线自测：打印非敏感配置（密钥只显示是否已配置）
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    s = get_settings()
    print(f"app : {s.app_name} ({s.app_env}) @ {s.app_host}:{s.app_port}")
    print(f"db  : {s.db_user}:***@{s.db_host}:{s.db_port}/{s.db_name}")
    print(f"llm : {s.deepseek_model_chat} @ {s.deepseek_base_url}")
    print(f"jwt : {s.jwt_algorithm} / 有效期 {s.jwt_access_token_expire_minutes} 分钟")
    print(f"providers: train={s.train_provider} hotel={s.hotel_provider} map={s.map_provider}")
    print(f"deepseek_api_key: {'已配置' if s.deepseek_api_key else '未配置'}")
