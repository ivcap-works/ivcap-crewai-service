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

# COPY requirements-dev.txt ./
# RUN pip install -r requirements-dev.txt --force-reinstall

# Get service files
ADD service.py ivcap_tool.py service_types.py ./

# So we can run it with --user
RUN mkdir /data && chmod 777 /data
RUN mkdir /.embedchain && chmod 777 /.embedchain
RUN mkdir /.local && chmod 777 /.local
RUN mkdir /.mem0 && chmod 777 /.mem0

# VERSION INFORMATION
ENV VERSION=0.0.1



# ALERT!!! Should NOT copy keys into docker container
ADD .env .

# Command to run
# Can't convince chromaDB to put the database file somewhere else
ENV CREWAI_STORAGE_DIR=/data
#RUN ln -s /data/out db
ENTRYPOINT ["python", "/app/service.py"]