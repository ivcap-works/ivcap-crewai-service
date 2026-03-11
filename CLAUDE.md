# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an IVCAP service that executes CrewAI crews (multi-agent AI workflows) with enterprise features including JWT authentication, artifact management, and knowledge sources. The service wraps CrewAI with IVCAP platform integration, enabling AI agents to work with platform artifacts and authenticate through LiteLLM proxy.

## Commands

### Development & Testing

```bash
# Install dependencies
poetry install --no-root

# Run service locally (port 8077)
poetry ivcap run

# Run with custom port
poetry ivcap run -- --port 8090

# Test locally (requires service running)
make test-local

# Test with authentication token
make test-local-with-auth
```

### Docker & Deployment

```bash
# Build Docker image locally
poetry ivcap docker-build

# Test Docker image
poetry ivcap docker-run

# Publish to IVCAP registry (may rebuild for target platform)
poetry ivcap docker-publish

# Register service on IVCAP
poetry ivcap service-register

# Register as AI tool (for agent discovery)
poetry ivcap tool-register
```

### Testing on IVCAP

```bash
# Execute job on IVCAP with streaming output
poetry ivcap exec-job crews/simple_crew.json -- --stream

# Submit job via Make (returns job ID)
make test-job-ivcap TEST_REQUEST=crews/simple_crew.json

# Check job result
make test-get-result-ivcap JOB_ID=<job-id>

# List all jobs for this service
make list-results-ivcap
```

### Utility Commands

```bash
# Generate SBOM (Software Bill of Materials)
make sbom

# Clean temporary files
make clean
```

## Architecture

### Request Flow

1. **Request Reception**: Service receives POST to `/` with CrewRequest JSON
2. **Authentication**: JWT token extracted from JobContext (4-path fallback)
3. **Artifact Download**: If `artifact-urns` provided, downloads to `runs/{job_id}/inputs/`
4. **Crew Loading**: Loads crew definition (inline or from IVCAP aspect reference)
5. **LLM Creation**: Creates authenticated LLM instances via LiteLLM proxy
6. **Knowledge Processing**: Converts `additional-inputs` to StringKnowledgeSource for RAG
7. **Tool Injection**: Auto-injects PDF/directory tools based on artifact file types
8. **Crew Execution**: Builds and executes CrewAI crew with task context chaining
9. **Output Capture**: Saves task outputs to `runs/{job_id}/outputs/*.md`
10. **Cleanup**: Removes artifact directory after execution

### Core Components

**service.py** (main entry point)
- `crew_runner()`: Main async endpoint handling crew execution
- `get_auth_token()`: Extracts JWT from JobContext (4 fallback paths)
- `load_crew_definition()`: Loads crew from inline or aspect reference
- `create_authenticated_llm()`: Creates LLM with JWT + embedder config
- `crew_wants_artifact_tools()`: Determines tool vs knowledge source mode

**service_types.py** (data models)
- `CrewA`: Pydantic model for crew specification (agents, tasks, process)
- `AgentA`: Agent definition with role, goal, backstory, tools, custom LLM
- `TaskA`: Task definition with context chaining support
- `ToolA`: Tool reference (URN-based or builtin)
- `as_crew()`: Converts CrewA → actual CrewAI Crew instance
- Tool registry via `add_supported_tools()` and factory pattern

**crew_builder.py** (task orchestration)
- `CrewBuilder`: Two-pass task construction:
  - Pass 1: Create all Task objects with auto-generated names
  - Pass 2: Resolve context references (task names OR agent names for legacy)
- Handles auto-chaining when no context specified
- Supports multi-task dependencies (one task can depend on multiple others)

**llm_factory.py** (LLM authentication)
- 3-tier authentication: LiteLLM proxy + JWT → proxy only → direct OpenAI
- `create_llm()`: Creates LLM with JWT token, model override, custom params
- `create_embedder_config()`: Creates embedder config for RAG tools (DirectorySearchTool, PDFSearchTool)
- Supports per-agent custom models (different agents can use different LLMs)

**artifact_manager.py** (artifact lifecycle)
- `download_artifacts()`: Downloads IVCAP artifacts to job-specific directory
- `cleanup()`: Removes artifact directory after execution
- Creates `runs/{job_id}/inputs/` structure for isolation

**knowledge_processor.py** (RAG integration)
- `create_knowledge_sources_from_inputs()`: Converts markdown strings → StringKnowledgeSource
- `create_knowledge_sources_from_artifacts()`: Converts artifact files → knowledge sources
- Enables crews to query previous research via semantic search

**ivcap_langgraph_tool.py** (LangGraph integration)
- `create_langgraph_tool()`: Wraps IVCAP LangGraph services as CrewAI tools
- Enables deep research agent integration (urn:ivcap:service:dcdc770b-d276-5df5-b5b7-babf17fa6eb7)

**events.py** (telemetry)
- `EventListener`: Captures CrewAI events for logging/monitoring
- Tracks agent actions, task completions, token usage

**vectordb.py** (vector database config)
- `create_vectordb_config()`: Creates Chroma/Qdrant config for RAG tools

### Request Schema

Crew execution requests wrap crew definitions:

```json
{
  "name": "execution_name",                    // Required
  "inputs": {"key": "value"},                  // Optional variables for {placeholders}
  "crew": { /* inline CrewA definition */ },   // Option 1: Inline crew
  "crew-ref": "urn:ivcap:aspect:...",          // Option 2: Reference to stored crew
  "artifact-urns": ["urn:ivcap:artifact:..."], // Optional: Download artifacts
  "additional-inputs": ["markdown..."],         // Optional: Previous crew outputs as knowledge
  "enable-citations": false                     // Optional: Citation tracking (experimental)
}
```

**Important**: Always wrap crew definitions in a request object. Sending crew JSON directly will fail with "Must provide either 'crew-ref' or 'crew' in request".

### Tool System

Tools are registered via URN in the `add_supported_tools()` registry:

- **Builtin Tools**: `urn:sd-core:crewai.builtin.{toolName}` (e.g., `serperDevTool`, `pdfSearchTool`)
- **IVCAP Services**: `urn:ivcap:service:{uuid}` (external service calls)
- **Factory Pattern**: Each tool URN maps to a factory function `(tool_def, context) -> BaseTool`

**Auto-Injection**: Service automatically injects tools based on artifact types:
- PDF files → `PDFSearchTool` to agents with research/search goals
- Text files → `DirectorySearchTool` to agents with research/search goals
- Triggered when agent has `DirectoryReadTool` OR "research"/"search" in goal

### Knowledge vs Tools Mode

**Tools Mode** (when crew has DirectoryReadTool OR research/search agents):
- Artifacts downloaded to `runs/{job_id}/inputs/`
- Tools (PDFSearchTool, DirectorySearchTool) auto-injected into agents
- Agents explicitly invoke tools to access files

**Knowledge Mode** (otherwise):
- Artifacts converted to StringKnowledgeSource objects
- All agents get automatic RAG access (no explicit tool invocation)
- Better for synthesis tasks where agents don't need file-level control

### Task Context Chaining

Tasks reference previous tasks by name in their `context` field:

```json
{
  "tasks": [
    {"name": "research", "agent": "researcher"},
    {"name": "write", "agent": "writer", "context": ["research"]},
    {"name": "edit", "agent": "editor", "context": ["research", "write"]}
  ]
}
```

- **Empty context `[]`**: First task, no dependencies
- **No context field**: Auto-chains to previous task
- **Task names**: Modern format (preferred)
- **Agent names**: Legacy format (still supported, resolves to agent's last task)

## Important Patterns

### JWT Authentication Flow

The service supports 4 fallback paths for extracting JWT tokens:
1. `job_ctxt.job_authorization` (ivcap-ai-tool v0.7.17+)
2. `job_ctxt.auth_token` (older versions)
3. `job_ctxt.headers['Authorization']` (HTTP headers)
4. `job_ctxt.request.headers['Authorization']` (nested request)

### LiteLLM Proxy Benefits

- Single JWT authenticates to all models (OpenAI, Anthropic, Google)
- Per-user cost tracking and quotas
- Model aliasing (e.g., "gpt-5" → actual available model)
- Centralized rate limiting
- No API keys stored in service code

### Job Isolation

Each job execution creates isolated directories:
- **Inputs**: `runs/{job_id}/inputs/` - artifact downloads
- **Outputs**: `runs/{job_id}/outputs/` - task outputs (*.md files)
- **Storage**: `runs/{job_id}/.crewai/` - RAG embeddings, memory

Set via `CREWAI_STORAGE_DIR` environment variable to prevent cross-job contamination.

### Embedder Configuration

RAG tools (DirectorySearchTool, PDFSearchTool) inherit embedder from Crew:

```python
embedder_config = factory.create_embedder_config(jwt_token)
crew = crew_def.as_crew(llm=llm, embedder=embedder_config, ...)
```

No need to pass embedder to individual tools - they automatically use crew's embedder.

## Configuration

### Environment Variables (.env or .env.local)

```bash
# LiteLLM Proxy (preferred authentication method)
LITELLM_PROXY_URL=https://litellm-proxy.ivcap.net
LITELLM_DEFAULT_MODEL=gpt-4.1
LITELLM_FALLBACK_MODEL=gpt-3.5-turbo

# IVCAP Platform
IVCAP_BASE_URL=https://develop.ivcap.net

# API Keys (fallback if no proxy)
OPENAI_API_KEY=sk-...
SERPER_API_KEY=...

# Telemetry (disable for production)
CREWAI_DISABLE_TELEMETRY=true
OTEL_SDK_DISABLED=true

# Storage (set per-job by service)
CREWAI_STORAGE_DIR=runs/{job_id}
```

### pyproject.toml Configuration

```toml
[tool.poetry-plugin-ivcap]
service-file = "service.py"
service-id = "urn:ivcap:service:01555c28-32d0-5839-b92b-f3e52410d6dd"
service-type = "lambda"
port = 8077
policy = "urn:ivcap:policy:ivcap.open.metadata"
```

## Testing

Comprehensive test files in `crews/` directory:
- `simple_crew.json`: Basic sequential workflow with web research
- `deep_search.json`: Multi-agent research with LangGraph integration
- `brainstorming.json`: Creative brainstorming workflow

Test request structure documented in TESTING_GUIDE.md with examples for:
- Basic crew execution
- Artifact download and file processing
- Knowledge sources (previous crew outputs)
- Per-agent custom models
- Task context chaining

## Common Issues

### "Must provide either 'crew-ref' or 'crew' in request"
You're sending crew JSON directly. Wrap it in a request object with `name` and `crew` fields.

### Tools return None / Agent creation fails
Artifact-dependent tools (DirectoryReadTool, FileReadTool) cannot be created without artifacts. Either:
- Provide `artifact-urns` in request
- Remove tools from agent definition
- Tools are automatically filtered if artifacts missing

### Task context not working
Verify task names match exactly in `context` array. Task names are case-sensitive.

### LLM authentication failed
Check JWT token extraction in logs. Look for "JWT token detected" message. If missing, verify IVCAP platform is passing authorization headers.

### RAG tools (PDFSearchTool) not working
Ensure embedder_config is set. Check logs for "Created embedder configuration for litellm proxy". Without embedder, RAG tools cannot create vector embeddings.

## Key Files Reference

- `service.py:357` - Main crew_runner endpoint
- `service_types.py:460` - CrewA.as_crew() - converts spec to Crew
- `crew_builder.py:30` - CrewBuilder.build_tasks() - task context resolution
- `llm_factory.py:64` - LLMFactory.create_llm() - authentication logic
- `artifact_manager.py:20` - download_artifacts() - artifact lifecycle
- `knowledge_processor.py:14` - create_knowledge_sources_from_inputs() - RAG setup
- `Makefile` - All common development commands
- `pyproject.toml` - Poetry dependencies and IVCAP service config
- `TESTING_GUIDE.md` - Comprehensive testing documentation with examples
