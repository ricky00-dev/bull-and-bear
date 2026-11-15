# 웹 정적 파일을 빌드해 Caddy 이미지에 넣는다. Caddy가 HTTPS(자동 인증서), 정적 파일, /api 프록시를 맡는다.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# 같은 출처에서 /api를 부르므로 API 주소는 비워 둔다 (CORS 불필요). Capacitor 앱 빌드 때만 절대 주소를 넣는다
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM caddy:2.8-alpine
COPY --from=build /src/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
