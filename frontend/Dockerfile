FROM node:22-alpine AS deps
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY . .
ARG ATLAS_API_URL=http://api:8000
ENV ATLAS_API_URL=$ATLAS_API_URL
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 web
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
