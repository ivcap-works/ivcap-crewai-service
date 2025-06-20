# IVCAP CrewAI Service

This directory implements a simple IVCAP service which takes a [CrewAI](https://www.crewai.com/)
_crew_ definition, executes it, and returns the results as an IVCAP artifact.


## 🧰 Prerequisites

Before starting, ensure you have the following installed:

- Python 3.9+
- Git (for cloning repositories)
- Docker to build the service container
- `curl` or `wget`


## Build & Deploy

Follow the steps below to build, test, and deploy this service:

- [Step 1: Install Poetry and IVCAP plugin](#step1)
- [Step 2: Install `ivcap` CLI Tool](#step2)
- [Step 3: Add and install Dependencies](#step3)
- [Step 4: Run and test locally](#step4)
- [Step 5: Deploying to IVCAP](#step5)
- [Step 6: Testing the service on IVCAP](#step6)

### Step 1: Install Poetry and IVCAP plugin <a name="step1"></a>

Poetry is a modern dependency and packaging manager for Python.

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

After installation, make sure Poetry is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Confirm installation:

```bash
poetry --version
```

Add the ICAP plugin to poetry:

```bash
poetry self add poetry-plugin-ivcap
```

ANd confirm the installation of the plugin:

```bash
poetry ivcap version
```
---
### Step 2: Install `ivcap` CLI Tool <a name="step2"></a>

The application relies on the `ivcap` CLI. You can install it from [ivcap-cli GitHub Releases](https://github.com/ivcap-works/ivcap-cli#install-released-binaries):

### For macOS/Linux

```bash
curl -Lo ivcap https://github.com/ivcap-works/ivcap-cli/releases/latest/download/ivcap-$(uname)-amd64
chmod +x ivcap
sudo mv ivcap /usr/local/bin/
```

### For Windows (PowerShell):

```powershell
Invoke-WebRequest -Uri https://github.com/ivcap-works/ivcap-cli/releases/latest/download/ivcap-Windows-amd64.exe -OutFile ivcap.exe
Move-Item ivcap.exe 'C:\Program Files\ivcap\ivcap.exe'
# Add C:\Program Files\ivcap to your PATH if necessary
```

Verify installation:

```bash
ivcap --help
```

---

### Step 3: Install Dependencies <a name="step3"></a>

To install the packages, run:

```bash
poetry install --no-root
```

---

### Step 4: Run and test locally <a name="step4"></a>

Ensure you have an OPENAI_API_KEY set in your environment, or in a .env file.

In one terminal window, start the service:

```bash
poetry ivcap run
```

In a different terminal window, use `curl` (or `wget`) to directly call the service:

```bash
make test-local
```

---

### Step 5: Deploying to IVCAP <a name="step5"></a>

To deploy a service or tool to IVCAP, we need to do the following:

* Build and publish the service as a Docker container
* Register the service
* Register the service as a tool

#### Build and publish the service as a Docker container

To test our setup, we will first build the docker image locally:

```bash
poetry ivcap docker-build
```

You can test the docker image with:
```bash
poetry ivcap docker-run
```

This should create a service listening on the same port as in the above "Run and test locally" step. The same 'make test-local' test should succeed and return the same results.

After verifying that the docker container build successfully, we can now deploy it:

```
poetry ivcap docker-publish
```

This may build a new container if your CPU architecture is different to the one of the respective IVCAP cluster. This is likely the case if your development machine is using an ARM CPU (like Apple Silicon).

#### Register the service

To register this tool we can again simply invoke the respective poetry command:

```bash
poetry ivcap service-register
```

#### Register the service as AI tool

To make this service discoverable by AI agents operating on the platform, we need to
upload the necessary description of this service to IVCAP. The `poetry ivcap service-register` command will create that description from the doc-string of the `map_go_terms` function
as well as its parameters. It is therefore very important to not only provide comprehensive
description of the core service function, but also add sufficient descriptions and examples to the parameter declarations. The above `Request` and `Result` models provide a good example on how to do this.

```bash
poetry ivcap tool-register
```
---

### Step 6: Testing the service on IVCAP <a name="step6"></a>

To test the service we have deployed in the previous step we can follow the same sequence as in
[Run and test locally](#step7). We can use the same test request `two_bp.json`.

```bash
TOKEN=$(ivcap context get access-token --refresh-token); \
URL=$(ivcap context get url)/1/services2/$(poetry ivcap --silent get-service-id)/jobs; \
curl -i -X POST \
    -H "content-type: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "timeout: 60" \
    --data @crews/simple_crew.json \
    ${URL}
```