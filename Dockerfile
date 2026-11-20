# Stage 1: build the React client (optional; the API falls back to web/ without it).
FROM node:22-slim AS webapp
WORKDIR /webapp
COPY webapp/package*.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

# Stage 2: API.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
COPY scripts ./scripts
COPY --from=webapp /webapp/dist ./webapp/dist
RUN useradd --system --uid 10001 appuser && mkdir /data && chown appuser /data
USER appuser
# Secrets (JWT_SECRET, CONFIRMATION_HMAC_SECRET, ...) come from the environment.
ENV APP_ENV=production DATABASE_URL=sqlite+aiosqlite:////data/dental_agent.db
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
