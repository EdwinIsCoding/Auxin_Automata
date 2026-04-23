FROM node:20-slim

WORKDIR /app
COPY package.json pnpm-lock.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile 2>/dev/null || pnpm install
COPY . .

ENV PORT=3002
EXPOSE 3002
CMD ["node", "server.mjs"]
