# ReviZoR FranK — Multi-stage Docker build
# Runs both the FastAPI auth server and the Streamlit app
# Nginx (separate container) handles routing and HTTPS

FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-server.txt

# Copy application code
COPY revizor_frank/ ./revizor_frank/
COPY server/ ./server/

# Create data directory
RUN mkdir -p revizor_frank/storage/data revizor_frank/exports

# Non-root user for security
RUN useradd -m -u 1000 revizor && chown -R revizor:revizor /app
USER revizor

EXPOSE 8000 8501
