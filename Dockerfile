# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final stage
FROM python:3.11-slim

# Ensure Python output is sent straight to terminal without buffering
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (e.g. for PyMuPDF if needed, but it usually comes with wheels)
# PyMuPDF might need libmupdf but wheels are self-contained

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p outputs

# Expose API port
EXPOSE 8000

# Run the API server
CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

