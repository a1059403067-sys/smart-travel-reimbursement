# frontend Dockerfile（构建上下文 = 项目根目录，见 docker-compose.yml build.context）
# 多阶段：node 构建 dist → nginx 静态托管 + /api 反代 backend:8006
FROM node:20-alpine AS build

WORKDIR /app

# npmmirror 加速（与本地开发 .npmrc 一致）
COPY frontend/package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:alpine

# 构建产物
COPY --from=build /app/dist /usr/share/nginx/html
# nginx 配置：静态托管 + /api 反代
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
