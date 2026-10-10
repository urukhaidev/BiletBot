FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY biletbot ./biletbot
RUN pip install --no-cache-dir .
CMD ["python", "-m", "biletbot"]
