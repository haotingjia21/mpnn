# syntax=docker/dockerfile:1

FROM python:3.11-slim

# 1) Install git (only needed to clone ProteinMPNN during build)
RUN apt-get update && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*

# 2) Pin ProteinMPNN by commit SHA (default = v1.0.1 commit shown on GitHub releases)
ARG PROTEIN_MPNN_SHA=905b008

# 3) Shallow-fetch exactly that commit into /opt/ProteinMPNN (small + reproducible)
RUN mkdir -p /opt/ProteinMPNN \
 && git init /opt/ProteinMPNN \
 && git -C /opt/ProteinMPNN remote add origin https://github.com/dauparas/ProteinMPNN.git \
 && git -C /opt/ProteinMPNN fetch --depth 1 origin ${PROTEIN_MPNN_SHA} \
 && git -C /opt/ProteinMPNN checkout FETCH_HEAD

# 4) Runtime config for your wrapper
ENV PROTEIN_MPNN_SCRIPT=/opt/ProteinMPNN/protein_mpnn_run.py \
    MPNN_JOBS_DIR=/data/runs/jobs \
    MPNN_TIMEOUT_SEC=600 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 5) Copy and install your wrapper (editable install + mpnn extras e.g. torch)
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY requests /app/requests

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir -e ".[mpnn]"

# 6) Output location (mount /data/runs on host if you want persistence)
RUN mkdir -p /data/runs/jobs
VOLUME ["/data/runs"]

EXPOSE 8000
CMD ["uvicorn", "mpnn_app.api:app", "--host", "0.0.0.0", "--port", "8000"]
