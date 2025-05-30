FROM python:3.11-slim-bookworm AS builder

# Install required systems libraries
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  git sqlite3 && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

RUN pip install -U pip
RUN pip install poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && poetry install --no-root

# COPY requirements-dev.txt ./
# RUN pip install -r requirements-dev.txt --force-reinstall

# Get service files
ADD service.py ivcap_tool.py service_types.py vectordb.py ./

# So we can run it with --user
RUN mkdir /data && chmod 777 /data
RUN mkdir /.embedchain && chmod 777 /.embedchain
RUN mkdir /.local && chmod 777 /.local
RUN mkdir /.mem0 && chmod 777 /.mem0

# VERSION INFORMATION
ARG VERSION ???
ENV VERSION=$VERSION

# ALERT!!! Should NOT copy keys into docker container
ADD .env .

# Command to run
ENV CREWAI_STORAGE_DIR=/data

ENTRYPOINT ["python", "/app/service.py"]
