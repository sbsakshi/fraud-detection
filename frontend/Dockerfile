FROM node:20-alpine

WORKDIR /app

# Lockfile first so installs are reproducible and the layer caches until deps change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . ./

EXPOSE 5173

# Dev server (hot reload) for local docker-compose; `npm run build` produces the static bundle.
CMD ["npm", "run", "dev"]
