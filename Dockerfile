FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && find dist -type f -name '*.js' -exec sed -i 's|http://localhost:8000||g' {} +

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV CACHE_DIR=/tmp/market-research-cache
ENV PORT=8000

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
