FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install build dependencies for cryptography/bcrypt + git for template cloning
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# kustomize: validate generated overlays before pushing to infra-gitops
ARG KUSTOMIZE_VERSION=5.4.3
RUN curl -fsSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv${KUSTOMIZE_VERSION}/kustomize_v${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin kustomize \
    && chmod +x /usr/local/bin/kustomize \
    && kustomize version

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify imports during build to fail early if dependencies are missing
RUN python -c "import fastapi; import jose; import passlib; import bcrypt; import jinja2; print('Build verification successful')"

# Expose port (default FastAPI)
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
