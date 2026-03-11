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

# Get service files
ADD service.py ivcap_tool.py service_types.py vectordb.py events.py logging.json utils.py llm_factory.py artifact_manager.py crew_builder.py ./
ADD ivcap_langgraph_tool.py ./
ADD tools/ ./tools/

# So we can run it with --user
RUN mkdir /data && chmod 777 /data
RUN mkdir /.embedchain && chmod 777 /.embedchain
RUN mkdir /.local && chmod 777 /.local
RUN mkdir /.mem0 && chmod 777 /.mem0

# VERSION INFORMATION
ARG VERSION 2.0.0
ENV VERSION=$VERSION

# ALERT!!! Should NOT copy keys into docker container
# ADD .env .

# Command to run
ENV CREWAI_STORAGE_DIR=/data
ENV ANONYMIZED_TELEMETRY=False
ENV LITELLM_DEFAULT_MODEL=gpt-4.1
ENV LITELLM_FALLBACK_MODEL=gpt-4o
ENV LITELLM_GEMINI_MODEL=gemini-2.5-pro
ENV IVCAP_RUNS_BASE_DIR=/tmp

ENTRYPOINT ["python", "/app/service.py", "--port", "80"]
