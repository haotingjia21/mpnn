# syntax=docker/dockerfile:1

FROM python:3.11-slim

# ---- system deps ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
  && rm -rf /var/lib/apt/lists/*

# ---- clone upstream ProteinMPNN (pinned by tag) ----
# Pin to a release tag for reproducible builds.
ARG PROTEIN_MPNN_TAG=v1.0.1
RUN git clone --depth 1 --branch "$PROTEIN_MPNN_TAG" https://github.com/dauparas/ProteinMPNN.git /opt/ProteinMPNN

ENV PROTEIN_MPNN_DIR=/opt/ProteinMPNN \
    PROTEIN_MPNN_SCRIPT=/opt/ProteinMPNN/protein_mpnn_run.py \
    MPNN_JOBS_DIR=/data/runs/jobs \
    MPNN_TIMEOUT_SEC=600 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install wrapper deps
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY requests /app/requests

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir -e ".[mpnn]"

# runtime output dir (volume-mount recommended)
RUN mkdir -p /data/runs/jobs
VOLUME ["/data/runs"]

EXPOSE 8000

CMD ["uvicorn", "mpnn.api:app", "--host", "0.0.0.0", "--port", "8000"]
