# @Date: 2026-05-30
# @Author: xisy
# @Discription: EduWeave 前端镜像（Vite 构建 + nginx 托管静态产物并反代 /api 到后端内网）

# ---- 构建阶段：编译 Vite 产物 ----
FROM node:20-alpine AS build
WORKDIR /app

# 构建期 API 基地址：留空即可。生产由 nginx 同源反代 /api 到后端，
# 前端运行时自动回退到 window.location.origin，无需在此写死后端域名。
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# 先装依赖，利用层缓存
COPY package.json package-lock.json ./
RUN npm ci

# 复制源码并构建（.env 已在 .dockerignore 中排除，避免本地开发地址污染产物）
COPY . .
RUN npm run build

# ---- 运行阶段：nginx 托管并反代 ----
FROM nginx:alpine

# 自定义站点配置：SPA 路由回退 + /api 反向代理 + SSE 流式支持
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# 与 nginx.conf 中 listen 端口一致，Zeabur 据此对外暴露
EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
