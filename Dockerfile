FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git pkg-config libsystemd-dev build-essential  && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN pip install pdm 

COPY . .

RUN pdm install

EXPOSE 8008
EXPOSE 5353/udp
EXPOSE 50003-50500

CMD ["pdm", "run", "sarad_registration_server"]

