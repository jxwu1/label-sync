# 构建上下文必须是仓库根（tokens 单源在 static/css/）：
#   docker build -f frontend/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /repo
COPY static/css/ static/css/
COPY frontend/ frontend/
WORKDIR /repo/frontend
RUN npm ci && npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist/ /usr/share/nginx/html/ui/
