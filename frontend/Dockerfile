# Multi-stage: `dev` is the hot-reload Vite server (docker-compose.dev.yml),
# `prod` is the static bundle served by nginx (the default in docker-compose.yml).

FROM node:20-alpine AS deps
WORKDIR /app
# Lockfile first so installs are reproducible and the layer caches until deps change.
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
COPY . ./
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM deps AS build
# Baked into the bundle at build time: where the *browser* reaches the API.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY . ./
RUN npm run build

FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q --spider http://127.0.0.1/ || exit 1
