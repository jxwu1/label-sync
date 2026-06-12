# 构建上下文必须是仓库根（tokens 单源在 static/css/）：
#   docker build -f frontend/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /repo
# lockfile 先行：源码改动不破坏 npm ci 缓存层（devDeps 体积大，缓存价值高）
COPY frontend/package.json frontend/package-lock.json frontend/
WORKDIR /repo/frontend
RUN npm ci
WORKDIR /repo
COPY static/css/ static/css/
COPY frontend/ frontend/
WORKDIR /repo/frontend
RUN npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist/ /usr/share/nginx/html/ui/
