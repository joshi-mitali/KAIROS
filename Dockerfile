FROM node:22-bookworm-slim AS frontend
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 KAIROS_WEB_HOST=0.0.0.0 PORT=8000 KAIROS_WEB_DIST=/app/web/dist KAIROS_RUNTIME_DIR=/app/data/runtime KAIROS_DATA_DIR=/app/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY kairos/ ./kairos/
COPY kairos_config/ ./kairos_config/
COPY collectors/ ./collectors/
COPY schemas/ ./schemas/
RUN pip install --no-cache-dir . && useradd --create-home kairos && mkdir -p data && chown kairos:kairos data
COPY --from=frontend /build/web/dist ./web/dist/
USER kairos
EXPOSE 8000
CMD ["kairos-web"]
