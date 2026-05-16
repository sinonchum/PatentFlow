# --- Build stage ---
FROM node:20-alpine AS builder

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json* /app/
RUN npm ci

COPY . /app

# NEXT_PUBLIC_* vars are baked at build time
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ARG NEXT_PUBLIC_PATENTFLOW_API_KEY=
ENV NEXT_PUBLIC_PATENTFLOW_API_KEY=${NEXT_PUBLIC_PATENTFLOW_API_KEY}
ARG NEXT_PUBLIC_VOICE_SERVER_URL=http://localhost:7860
ENV NEXT_PUBLIC_VOICE_SERVER_URL=${NEXT_PUBLIC_VOICE_SERVER_URL}

RUN npm run build

# --- Production stage ---
FROM node:20-alpine AS runner

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm install -g serve

COPY --from=builder /app/out ./out

EXPOSE 3000

CMD ["serve", "-s", "out", "-l", "3000"]
