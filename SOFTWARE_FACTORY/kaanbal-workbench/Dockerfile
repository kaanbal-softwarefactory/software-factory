FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git bash coreutils util-linux nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home worker
USER 10001:10001
WORKDIR /workspace
CMD ["python", "-I", "-c", "import time; time.sleep(3600)"]
