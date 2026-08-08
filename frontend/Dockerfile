ARG BASE_REGISTRY=docker.m.daocloud.io/library

FROM ${BASE_REGISTRY}/node:18-alpine AS build-stage

WORKDIR /app

# 复制依赖文件
COPY package*.json ./
RUN npm ci --no-audit --no-fund

# 复制源代码
COPY . .

# 构建应用
RUN npm run build

# 生产环境
FROM ${BASE_REGISTRY}/nginx:alpine AS production-stage
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
