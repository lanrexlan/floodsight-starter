FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY api ./api
COPY floodsight ./floodsight
COPY dashboard ./dashboard
COPY scripts/prepare_release_assets.py ./scripts/prepare_release_assets.py
COPY data/processed ./data/processed
COPY data/models ./data/models
COPY floodsight.html privacy.html ./
RUN python scripts/prepare_release_assets.py && useradd --uid 10001 --create-home floodsight && chown -R floodsight:floodsight /app
USER floodsight
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
