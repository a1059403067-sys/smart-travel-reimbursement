# API 路由聚合（架构方案 api/router.py：前缀+tags 聚合）
# 新增模块路由在此登记；main.py 只 include 一次 api_router
from fastapi import APIRouter

from backend.api.v1.analytics import router as analytics_router
from backend.api.v1.auth import router as auth_router
from backend.api.v1.invoice import router as invoice_router
from backend.api.v1.reimbursement import router as reimbursement_router
from backend.api.v1.travel import router as travel_router
from backend.api.v1.unified_chat import router as unified_chat_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(analytics_router)
api_router.include_router(invoice_router)
api_router.include_router(reimbursement_router)
api_router.include_router(travel_router)
api_router.include_router(unified_chat_router)
