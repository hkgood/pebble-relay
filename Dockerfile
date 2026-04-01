FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask pyyaml bcrypt

# Copy code
COPY server.py .

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8977

# Environment variables
ENV CONFIG_PATH=/data/config.yaml
ENV DB_PATH=/data/relay.db
ENV PORT=8977

CMD ["python", "server.py"]
