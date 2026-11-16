# syntax=docker/dockerfile:1

FROM node:22-alpine AS build
WORKDIR /app

# Install exactly the locked dependency tree.
COPY package.json package-lock.json* ./
RUN npm install --include=dev

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV BACKEND_HOST=opencs-backend \
    BACKEND_PORT=8000 \
    HUB_HOST=jupyterhub \
    HUB_PORT=8000 \
    NGINX_ENVSUBST_FILTER="^(BACKEND_HOST|BACKEND_PORT|HUB_HOST|HUB_PORT)$"
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1
