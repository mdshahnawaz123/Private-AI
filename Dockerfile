FROM node:22-bookworm-slim AS fragments
WORKDIR /converter
COPY tools/fragments/package.json tools/fragments/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.container.txt .
RUN pip install --no-cache-dir -r requirements.container.txt && pip check

# Copy application
COPY . .
COPY --from=fragments /usr/local/bin/node /usr/local/bin/node
COPY --from=fragments /converter/node_modules /app/tools/fragments/node_modules

# Create data directory
RUN mkdir -p /data
RUN useradd --create-home --uid 10001 expo && chown -R expo:expo /app /data
USER expo

# Expose port
EXPOSE 8090

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-access-log"]
