FROM python:3.11-slim

# Install OpenSSL and Speech SDK native dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    ca-certificates \
    libssl-dev \
    libasound2 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate PKI artifacts
RUN bash scripts/setup_all.sh

# Set TMPDIR for CRL cache observation
ENV TMPDIR=/app/tmp_crl_cache
RUN mkdir -p /app/tmp_crl_cache

# Default: run full reproduction scenario
CMD ["python", "src/reproduce.py"]
