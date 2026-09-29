FROM node:24.18.0-alpine AS build
WORKDIR /app
ARG VITE_DEMO_ACCESS_HINT=false
ENV VITE_DEMO_ACCESS_HINT=$VITE_DEMO_ACCESS_HINT
RUN corepack enable && corepack prepare pnpm@11.19.0 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG VITE_DEMO_ACCESS_HINT=false
ENV VITE_DEMO_ACCESS_HINT=$VITE_DEMO_ACCESS_HINT
RUN pnpm build

FROM nginx:1.29.1-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
