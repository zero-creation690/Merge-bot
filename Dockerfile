FROM python:3.11-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create directory for temporary files
RUN mkdir -p /tmp/downloads

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose health check port for Koyeb
EXPOSE 8000

# Run the bot
CMD ["python", "main.py"]
