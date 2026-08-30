FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS dependencies

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

FROM dependencies AS builder

COPY apps/web apps/web
RUN mkdir -p apps/web/public

ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --dir apps/web build

FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx \
    && addgroup --system --gid 10001 geo \
    && adduser --system --uid 10001 --ingroup geo geo

COPY --from=builder --chown=geo:geo /app/apps/web/.next/standalone ./
COPY --from=builder --chown=geo:geo /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=geo:geo /app/apps/web/public ./apps/web/public

USER 10001:10001
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
