# Stage 1: build the React console (Vite + TypeScript + Tailwind)
FROM node:20-alpine AS console
WORKDIR /console
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: install the Python app into an isolated virtualenv
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
COPY mcp ./mcp
RUN pip install .

# Stage 3: runtime. One image, two entrypoints (api / upstreams). Runs as a non-root user.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH \
    SPEC_PATH=/app/openapi.yaml CONSOLE_DIR=/app/console DB_PATH=/data/platform.db
RUN useradd --uid 10001 --create-home app && mkdir -p /data && chown app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY openapi.yaml ./openapi.yaml
COPY --from=console /console/dist ./console
USER app
EXPOSE 8080 8081
CMD ["python", "-m", "support_platform"]
