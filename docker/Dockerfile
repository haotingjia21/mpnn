FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Basic runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install python deps (CPU torch)
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir numpy \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy repo
COPY . /app

# If you have a proper pyproject, install your wrapper package too (optional but nice)
# If this fails due to missing metadata, you can delete these two lines.
RUN pip install --no-cache-dir -e .

# Default to the CLI
ENTRYPOINT ["python", "-m", "mpnn_app.cli_design"]
