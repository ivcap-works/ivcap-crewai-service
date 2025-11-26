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
ADD service.py ivcap_tool.py service_types.py vectordb.py events.py logging.json no_posthog.py utils.py llm_factory.py artifact_manager.py crew_builder.py ./

# So we can run it with --user
RUN mkdir /data && chmod 777 /data
RUN mkdir /.embedchain && chmod 777 /.embedchain
RUN mkdir /.local && chmod 777 /.local
RUN mkdir /.mem0 && chmod 777 /.mem0

# VERSION INFORMATION
ARG VERSION ???
ENV VERSION=$VERSION

# ALERT!!! Should NOT copy keys into docker container
# ADD .env .

# Command to run
ENV CREWAI_STORAGE_DIR=/data
ENV ANONYMIZED_TELEMETRY=False
ENV IVCAP_BASE_URL=https://develop.ivcap.net
ENV OPENAI_BASE_URL=https://mindweaver.develop.ivcap.io/litellm/v1
ENV LITELLM_PROXY_URL=https://mindweaver.develop.ivcap.io/litellm/v1
# ENV SERPER_API_KEY=1c886156ad5807d278daa2a31f78336254a601af

ENTRYPOINT ["python", "/app/service.py", "--port", "80"]
