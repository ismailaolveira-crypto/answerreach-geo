FROM node:22-alpine

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web

ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
RUN pnpm --dir apps/web build

ENV NODE_ENV=production
EXPOSE 3000
CMD ["pnpm", "--dir", "apps/web", "start", "--hostname", "0.0.0.0", "--port", "3000"]
