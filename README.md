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
env VERSION="|87f9056|2025-04-06T17:39+10:00" \
                python ../service.py --port 8077
.... lots of deprecation warnings from crewAI tools library
2025-04-06T17:39:29+1000 INFO (app): OTEL_SDK_DISABLED=true
2025-04-06T17:39:29+1000 INFO (app): CrewAI Agent Runner - |87f9056|2025-04-06T17:39+10:00 - v0.5.9
/opt/homebrew/Caskroom/miniconda/base/envs/crewai/lib/python3.11/site-packages/websockets/legacy/__init__.py:6: DeprecationWarning: websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html for upgrade instructions
  warnings.warn(  # deprecated in 14.0 - 2024-11-09
/opt/homebrew/Caskroom/miniconda/base/envs/crewai/lib/python3.11/site-packages/uvicorn/protocols/websockets/websockets_impl.py:17: DeprecationWarning: websockets.server.WebSocketServerProtocol is deprecated
  from websockets.server import WebSocketServerProtocol
2025-04-06T17:39:29+1000 INFO (uvicorn.error): Started server process [7134]
2025-04-06T17:39:29+1000 INFO (uvicorn.error): Waiting for application startup.
2025-04-06T17:39:29+1000 INFO (uvicorn.error): Application startup complete.
2025-04-06T17:39:29+1000 INFO (uvicorn.error): Uvicorn running on http://0.0.0.0:8077 (Press CTRL+C to quit
```

The service is now waiting at local port 8077 for requests. The Makefile already defines a
target to use curl to send such request. In a different terminal, issue the following:

### Testing with Simple Crew

```
% make test-local
curl \
                -X POST \
                -H "Timeout: 360" \
                -H "content-type: application/json" \
                --data @crews/simple_crew.json  \
                http://localhost:8077 | jq
... some updatrs from curl while waiting for a result
{
  "$schema": "urn:sd:schema:icrew.answer.2",
  "answer": "---\n\n**Exploring the Future: How AI is Shaping Our World in 2024**\n\nThe digital frontier is ever-evolving, and at the forefront of this transformation is artificial intelligence (AI). In 2024, AI is not just a buzzword but a significant force reshaping industries and enhancing our daily lives. Let's dive into how AI is breaking barriers and setting new benchmarks across various sectors.\n\n**Riding the Wave of the Generative AI Boom**\n\nOne of the most exciting trends in 2024 is the generative AI boom. Businesses worldwide are riding this wave to revolutionize content creation and customer interaction. ...
  ....

  "created_at": "2025-04-06T17:45:00+10:00",
  "process_time_sec": 0.6114650000000004,
  "run_time_sec": 55.399178981781006,
  "token_usage": {
    "total_tokens": 32049,
    "prompt_tokens": 29808,
    "cached_prompt_tokens": 14848,
    "completion_tokens": 2241,
    "successful_requests": 10
  }
}
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
% make docker-run
docker run -it \
                -p 8077:8077 \
                --platform=linux/arm64 \
                --rm \
                crew_ai_service_arm64 --port 8077
.... lots of deprecation warnings from crewAI tools library
2025-04-06T07:51:26+0000 INFO (uvicorn.error): Started server process [1]
2025-04-06T07:51:26+0000 INFO (uvicorn.error): Waiting for application startup.
2025-04-06T07:51:26+0000 INFO (uvicorn.error): Application startup complete.
2025-04-06T07:51:26+0000 INFO (uvicorn.error): Uvicorn running on http://0.0.0.0:8077 (Press CTRL+C to quit)
```

Again, see the `Makefile` for various testing scenarios.