FROM python:3.11-slim-bookworm AS builder

# Install required systems libraries
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  git sqlite3 && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install -U pip
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt --force-reinstall

# Get service files
ADD crew_ai_service.py ivcap_tool.py builtin_tools.json ./
RUN mv crew_ai_service.py service.py

# So we can run it with --user
RUN mkdir /.embedchain && chmod 777 /.embedchain
RUN mkdir /.local && chmod 777 /.local
RUN mkdir /.mem0 && chmod 777 /.mem0

# VERSION INFORMATION
ARG GIT_TAG ???
ARG GIT_COMMIT ???
ARG BUILD_DATE ???

ENV IVCAP_SERVICE_VERSION $GIT_TAG

ENV IVCAP_SERVICE_COMMIT $GIT_COMMIT
ENV IVCAP_SERVICE_BUILD $BUILD_DATE

# ALERT!!! Should NOT copy keys into docker container
ADD .env .

# Command to run
RUN mkdir -p /data/in /data/out /cache
# Can't convince chromaDB to put the database file somewhere else
RUN ln -s /data/out db
ENTRYPOINT ["python", "/app/service.py"]