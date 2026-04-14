FROM node:20-slim AS base

RUN corepack enable && corepack prepare pnpm@9.5.0 --activate

WORKDIR /app

# ── deps ──────────────────────────────────────────────────────────────────────
FROM base AS deps
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ── builder ───────────────────────────────────────────────────────────────────
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY dashboard/ .

# Build args become env vars at build time
ARG NEXT_PUBLIC_BRIDGE_WS_URL=ws://bridge:8766
ARG NEXT_PUBLIC_TWIN_WS_URL=ws://twin:8765
ARG NEXT_PUBLIC_PROGRAM_ID
ARG NEXT_PUBLIC_HELIUS_RPC_URL
ARG NEXT_PUBLIC_AGENT_PUBKEY

ENV NEXT_PUBLIC_BRIDGE_WS_URL=$NEXT_PUBLIC_BRIDGE_WS_URL
ENV NEXT_PUBLIC_TWIN_WS_URL=$NEXT_PUBLIC_TWIN_WS_URL
ENV NEXT_PUBLIC_PROGRAM_ID=$NEXT_PUBLIC_PROGRAM_ID
ENV NEXT_PUBLIC_HELIUS_RPC_URL=$NEXT_PUBLIC_HELIUS_RPC_URL
ENV NEXT_PUBLIC_AGENT_PUBKEY=$NEXT_PUBLIC_AGENT_PUBKEY

RUN pnpm build

# ── runner ────────────────────────────────────────────────────────────────────
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
