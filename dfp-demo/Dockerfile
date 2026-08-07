FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Deloitte-UK-Innersource/morpheus-dfp"
LABEL org.opencontainers.image.description="Morpheus Digital Fingerprinting Platform"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY modules/ ./modules/
COPY pipelines/ ./pipelines/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY pyproject.toml .
COPY README.md .

# Install package
RUN pip install --no-cache-dir -e .

# Create directories for data and outputs
RUN mkdir -p /app/data/input /app/data/output/detections /app/data/output/profiles /app/data/logs /app/data/mlflow

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV MLFLOW_TRACKING_URI=http://localhost:5001

# Expose ports for services
EXPOSE 8000 9090 9091

# Default command
CMD ["python", "-m", "pipelines.inference_pipeline", "--help"]
