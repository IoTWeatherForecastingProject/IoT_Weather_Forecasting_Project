# Build from the repository root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

ARG INSTALL_INFERENCE=false
WORKDIR /app/backend

# libgomp is required by the delivered XGBoost CPU inference runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-inference.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_INFERENCE" = "true" ]; then \
        pip install --no-cache-dir -r requirements-inference.txt; \
    fi

# Explicit copies exclude local .env credentials and virtual environments.
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY ml/__init__.py ml/inference_engine.py ml/feature_engineering.py /app/ml/
COPY ml/models/*.joblib ml/models/feature_schema.json /app/ml/models/
COPY ai_engine/common /app/ai_engine/common
COPY ai_engine/inference /app/ai_engine/inference
COPY ai_engine/temperature_forecasting /app/ai_engine/temperature_forecasting
COPY ai_engine/rain_classification /app/ai_engine/rain_classification
COPY ai_engine/sensor_analytics /app/ai_engine/sensor_analytics
COPY ai_engine/openweather_benchmark /app/ai_engine/openweather_benchmark
COPY ai_engine/saved_models /app/ai_engine/saved_models

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

