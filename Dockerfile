# Stage 1: Build environment
FROM python:3.13-slim AS builder
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git pkg-config libsystemd-dev build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip install pdm
COPY . .
RUN pdm install --prod --no-editable

# Stage 2: Runtime environment
FROM python:3.13-slim
WORKDIR /app

# Install only necessary runtime libraries if required (e.g., libsystemd0 instead of libsystemd-dev)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libsystemd0 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY . .

EXPOSE 8008 5353/udp 50003-50500
CMD ["/app/.venv/bin/sarad_registration_server"]
