# IVCAP CrewAI Service

This directory implements a simple IVCAP service which takes a [CrewAI](https://www.crewai.com/)
_crew_ definition, executes it, and returns the results as an IVCAP artifact.

* [Development Setup](#setup)
* [Build & Deployment Service](#build-deployment)


## Development Setup <a name="setup"></a>

### Python

First, we need to setup a Python environment. We are using `conda`, but `venv` is
also a widely used alternative

```
conda create --name crewai python=3.11 -y
conda activate crewai
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

> Important: You will also need to add a `.env` file containing your API_KEYS (depending
on the tools your crews are using)

.env:

```
OPENAI_API_KEY=your_openai_api_key
SERPER_API_KEY=your_serper_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
GOOGLE_API_KEY=your_google_api_key
```


### Initial Test of Service - Processing Queues

Finally, to check if everything is properly installed, use the `run` target to execute the
service locally:

```
% make run
env IVCAP_OUT_DIR=/.../_run_ \
        python crew_ai_service.py \
                --input /.../examples/queue \
                --output urn:ivcap:queue:/.../_run_/out
INFO 2024-11-15T17:24:14+1100 ivcap IVCAP Service 'crew-ai-runner' ?/? (sdk 0.8.0) built on ?.
INFO 2024-11-15T17:24:14+1100 ivcap Starting job for service 'crew-ai-runner' on node 'None' ..
INFO 2024-11-15T17:24:15+1100 service processing crew 'Simple Test Crew'
...
DEBUG 2024-11-15T17:25:24+1100 ivcap Queue#out pushing message id '1'
>>> Output should be in '/.../_run_/out'
```

At this point you should see a few files in the `./_run_/out` directory:

```
% ls ./_run_/out
00000001.json   _idx            _log.csv        _pending        _queue.lock
```

The `00000001.json` file contains the collected results and progress reports from the
various agents and tools employed.

### Initial Test of Service - HTTP Service

An alternative deployment is to run the service as an HTTP server waiting for requests:

```
% make run-http
env IVCAP_OUT_DIR=/.../_run_ \
        python crew_ai_service.py \
                --ivcap:service-url http://localhost:8077
INFO 2024-11-15T17:31:54+1100 ivcap IVCAP Service 'crew-ai-runner' ?/? (sdk 0.8.0) built on ?.
INFO 2024-11-15T17:31:54+1100 ivcap Starting job for service 'crew-ai-runner' on node 'None' (urn:ivcap:order:00000000-0000-0000-0000-000000000000)
INFO:     Started server process [6737]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://localhost:8077 (Press CTRL+C to quit)
```

The service is now waiting at local port 8077 for requests. The Makefile already defines a
target to use curl to send such request. In a different terminal, issue the following:

```
% make submit-request
curl -X POST -H "Content-Type: application/json" -d @/.../examples/simple_crew.json http://localhost:8077
{
  "$schema": "urn:sd:schema:icrew.answer.2",
  "answer": "Artificial Intelligence (AI) has been making significant strides in 2024, ...
  ...
```

## Build & Deployment Service <a name="build-deployment"></a>

An IVCAP service usually consists of a _service description_ and one or more docker
containers implementing the computation components of the service.

The included [Makefile](./Makefile) has already defined a few targets for these tasks.

### Build the Docker Container

For this example, we only require a single docker container as defined in [Dockerfile](./Dockerfile). To build it locally, use:

```
make docker-build
```

To locally test the docker container:
```
% make docker-run
...
docker run -it \
                -e IVCAP_INSIDE_CONTAINER="" \
                -e IVCAP_ORDER_ID=ivcap:order:0000 \
                -e IVCAP_NODE_ID=n0 \
                -e IVCAP_IN_DIR=/data/in \
                -e IVCAP_OUT_DIR=/data/out \
                -e IVCAP_CACHE_DIR=/data/cache \
                -v /.../examples:/data/in \
                -v /.../_run_:/data/out \
                -v /.../_run_:/data/cache \
                --user "502:20" \
                crew_ai_service \
                        --input /data/in/queue \
                        --output urn:ivcap:queue:/data/out
INFO 2024-11-15T06:36:45+0000 ivcap IVCAP Service 'crew-ai-runner' / (sdk 0.8.0) built on Fri Nov 15 15:44:38 AEDT 2024.
2024-11-15 06:36:45,733 - 281473314344992 - utils.py-utils:129 - INFO: IVCAP Service 'crew-ai-runner' / (sdk 0.8.0) built on Fri Nov 15 15:44:38 AEDT 2024.
INFO 2024-11-15T06:36:45+0000 ivcap Starting job for service 'crew-ai-runner' on node 'None' (ivcap:order:0000)
2024-11-15 06:36:45,734 - 281473314344992 - service.py-service:203 - INFO: Starting job for service 'crew-ai-runner' on node 'None' (ivcap:order:0000)
INFO 2024-11-15T06:36:45+0000 service processing crew 'Simple Test Crew'
