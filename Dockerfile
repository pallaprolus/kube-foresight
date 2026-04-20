FROM python:3.12-slim AS base

LABEL maintainer="Sudhakar Pallaprolu"
LABEL org.opencontainers.image.source="https://github.com/pallaprolus/kube-foresight"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 1000 kf && \
    useradd --uid 1000 --gid kf --create-home kf

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir -e ".[k8s,dashboard]"

# Copy source
COPY kube_foresight/ kube_foresight/

# Re-install with source in place
RUN pip install --no-cache-dir -e ".[k8s,dashboard]"

# Data directory for SQLite metrics store
RUN mkdir -p /data && chown kf:kf /data
VOLUME ["/data"]

USER kf

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

ENTRYPOINT ["kube-foresight"]
CMD ["dashboard", "--host", "0.0.0.0", "--port", "8080"]
