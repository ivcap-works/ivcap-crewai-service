# IVCAP CrewAI Service - Complete Testing Guide

**Updated**: Fresh testing guide for task context chaining implementation  
**Default Test Model**: gemini-2.5-flash

---

## ⚠️ **Important: Request Format**

This service is a **CrewAI runner** that executes various CrewAI crew definitions. Each crew definition can have different valid inputs (called "placeholders" in crew definitions). The service expects a **request wrapper** around your crew definition:

**WRONG** ❌ (sending crew JSON directly):
```bash
curl -d @examples/simple_crew2.json http://localhost:8077/
# Error: "Must provide either 'crew-ref' or 'crew' in request"
```

**CORRECT** ✅ (wrapping crew in request):
```bash
curl -d @examples/simple_crew2_request.json http://localhost:8077/
# OR
curl -d '{
  "name": "my_crew_execution",
  "inputs": {},
  "crew": <CREW_DEFINITION_HERE>
}' http://localhost:8077/
```

**Request Schema**:
```json
{
  "name": "execution_name",                      // Required
  "inputs": {"key": "value"},                    // Optional variables (varies by crew - see below)
  "crew": {...},                                 // Option 1: Inline crew definition
  "crew-ref": "urn:sd:crewai:crew.deepresearch", // Option 2: Reference to stored crew
  "artifact-urns": ["urn:..."]                   // Optional: Download artifacts
}
```

> **Note**: Valid inputs depend on the specific crew definition being executed. See the [Determining Valid Inputs](#-determining-valid-inputs) section below to learn how to find which inputs a crew expects.

---

## 📝 Determining Valid Inputs

This service is a **CrewAI runner** that executes various CrewAI crew definitions. Each crew definition can have different valid inputs.

### Terminology

- **Service Request**: Uses `inputs` (dictionary of key-value pairs)
- **Crew Definition**: Uses `placeholders` (array of placeholder names)
- **These are the same thing** - placeholders in the crew definition correspond to input keys in the service request

### How to Find Valid Inputs

To determine which inputs are valid for a specific crew, query the IVCAP Aspect that contains the crew definition:

```bash
curl -X GET "https://develop.ivcap.net/1/aspects/urn:ivcap:aspect:YOUR_ASPECT_URN" \
  -H 'accept: application/json' \
  -H "Authorization: Bearer $IVCAP_TOKEN"
```

The response will include a `placeholders` array in the `content` field:

```json
{
  "id": "urn:ivcap:aspect:1a32a472-ba89-49ac-8bf2-9434c8dff2a0",
  "entity": "urn:sd:crewai:crew.deepresearch",
  "schema": "urn:sd:schema:icrew-crew.1",
  "content": {
    "$entity": "urn:sd:crewai:crew.deepresearch",
    "$schema": "urn:sd:schema:icrew-crew.1",
    "placeholders": [
      "research_topic",
      "keywords",
      "additional_information"
    ],
    ...
  }
}
```

These placeholder names (e.g., `research_topic`) are what you use as keys in your `inputs` dictionary. They will be substituted wherever `{research_topic}` appears in the crew definition (agent goals, task descriptions, etc.).

### Example: Complete Working Request

Here's a complete example showing how to execute a crew with valid inputs:

```bash
curl -i -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${IVCAP_TOKEN}" \
    --data '{
  "name": "dan_test",
  "inputs": {
    "research_topic": "Top AI Trends in Software Engineering in last 3 months",
    "keywords": "AI, Software",
    "additional_information": ""
  },
  "crew-ref": "urn:ivcap:aspect:1a32a472-ba89-49ac-8bf2-9434c8dff2a0",
  "artifact-urns": []
}' \
    "https://develop.ivcap.net/1/services2/urn:ivcap:service:YOUR_SERVICE_URN/jobs"
```

**Response** (202 Accepted with retry-later pattern):

```json
{
  "$schema": "urn:ivcap:schema.service.retry-later",
  "job-id": "urn:ivcap:job:a91bc99b-ceb3-443a-af3a-714a6d6c7881",
  "location": "https://develop.ivcap.net/1/services2/.../jobs/a91bc99b-ceb3-443a-af3a-714a6d6c7881",
  "retry-later": 10
}
```

The service returns a 202 Accepted response with a `job-id` and `location` where you can check the job status.

---

## 📋 Prerequisites

### 1. Install Dependencies

```bash
cd /Users/ran12c/development/ivcapworks/ivcap-crewai-service
poetry install --no-root
export IVCAP_TOKEN=$(ivcap context get access-token --refresh-token)
export OPENAI_API_KEY=$IVCAP_TOKEN
export OPENAI_BASE_URL="https://mindweaver.develop.ivcap.io/litellm/v1"
export LITELLM_PROXY_URL="$OPENAI_BASE_URL"
poetry ivcap run 
```

### 2. Configure Environment

Create `.env` file in project root:

```bash
cat > .env <<'EOF'
# LiteLLM Proxy Configuration (using Gemini for testing)
LITELLM_PROXY_URL=https://litellm-proxy.ivcap.net
LITELLM_DEFAULT_MODEL=gemini-2.5-flash
LITELLM_FALLBACK_MODEL=gemini-2.0-flash-exp

# IVCAP Configuration
IVCAP_BASE_URL=https://develop.ivcap.net

# Disable telemetry
CREWAI_DISABLE_TELEMETRY=true
OTEL_SDK_DISABLED=true
EOF
```

### 3. Get IVCAP Authentication Token

```bash
# Option 1: Via IVCAP CLI
export IVCAP_TOKEN=$(ivcap context get-token)

# Option 2: Manual
export IVCAP_TOKEN="your-jwt-token-here"

# Verify token
echo $IVCAP_TOKEN | cut -c1-20
```

### 4. Verify Configuration

```bash
poetry run python -c "
import os
from llm_factory import get_llm_factory
factory = get_llm_factory()
print(f'✓ Proxy: {factory.litellm_proxy_url}')
print(f'✓ Default model: {factory.default_model}')
print(f'✓ Fallback model: {factory.fallback_model}')
"
```

**Expected Output**:
```
✓ Proxy: https://litellm-proxy.ivcap.net
✓ Default model: gemini-2.5-flash
✓ Fallback model: gemini-2.0-flash-exp
```

---

## 🚀 Starting the Service

### Method 1: Using Poetry IVCAP Plugin (Recommended)

```bash
poetry ivcap run
```

**Expected Output**:
```
INFO (app): Starting IVCAP CrewAI Service
INFO (app.llm_factory): LLMFactory initialized: proxy=https://litellm-proxy.ivcap.net, default_model=gemini-2.5-flash
INFO (uvicorn): Uvicorn running on http://0.0.0.0:8077
```

### Method 2: Direct Python with Custom Config

```bash
poetry run python service.py \
  --litellm-proxy https://litellm-proxy.ivcap.net \
  --default-model gemini-2.5-flash
```

### Method 3: With Environment Override

```bash
export LITELLM_DEFAULT_MODEL="gemini-2.0-flash-exp"
poetry ivcap run
```

### Verify Service is Running

```bash
# Check health
curl http://localhost:8077/api

# Should return: OpenAPI documentation page
```

---

## 🧪 Test Suite

### Test 1: Basic Crew Execution (Using Existing Crew)

**Purpose**: Verify core functionality works

**IMPORTANT**: Crew JSON files must be wrapped in a request object:

```bash
# Using the prepared request file
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/simple_crew2_request.json | jq .

# OR manually wrap the crew:
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "basic_test",
    "inputs": {
      "llm_model": "gemini-2.5-flash"
    },
    "crew": {
      "$schema": "urn:sd:schema.icrew.crew.2",
      "name": "simple_qa",
      "process": "sequential",
      "verbose": false,
      "agents": [{
        "name": "assistant",
        "role": "AI Assistant",
        "goal": "Answer questions accurately",
        "backstory": "You are a helpful AI assistant",
        "tools": []
      }],
      "tasks": [{
        "name": "answer_task",
        "description": "Answer: What are the key benefits of AI in healthcare?",
        "expected_output": "A comprehensive answer",
        "agent": "assistant"
      }]
    }
  }' | jq .
```

**Expected Response**:
```json
{
  "$schema": "urn:sd-core:schema.crewai.response.1",
  "answer": "AI in healthcare offers benefits like...",
  "crew_name": "basic_test",
  "task_responses": [...],
  "token_usage": {
    "total_tokens": 1234,
    "prompt_tokens": 567,
    "completion_tokens": 667
  },
  ...
}
```

**Validation**:
- ✅ Response received with 200 status
- ✅ `answer` field contains result
- ✅ `token_usage` shows Gemini usage
- ✅ Logs show: "✓ LLM created: gemini-2.5-flash via proxy with JWT"

---

### Test 2: Legacy Format - Agent Name Context (simple_crew2.json)

**Purpose**: Verify backward compatibility with existing crews

```bash
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/simple_crew2.json | jq .
```

**What's Being Tested**:
- `"context": ["initial_knowledge_base"]` → treated as no context
- `"context": ["researcher"]` → resolves to researcher's last task (agent name format)

**Expected Logs**:
```
INFO: Building 2 tasks (pass 1: creation)
DEBUG: Auto-generated task name: researcher_task_0
DEBUG: Created task 0: 'researcher_task_0' (agent: researcher)
DEBUG: Auto-generated task name: writer_task_1
DEBUG: Created task 1: 'writer_task_1' (agent: writer)
INFO: Resolving task context chains (pass 2)
DEBUG: Task 'researcher_task_0': 'initial_knowledge_base' keyword → no context
INFO: Task 'writer_task_1' → context agent: 'researcher' (resolved to task 'researcher_task_0') [LEGACY FORMAT]
INFO: Task 'writer_task_1' context resolved: ['researcher_task_0']
INFO: ✓ Built 2 tasks with context resolution complete
```

**Validation**:
- ✅ Writer task gets researcher's output as context
- ✅ Log shows "[LEGACY FORMAT]" for agent-name resolution
- ✅ No errors or warnings about unknown references

---

### Test 3: New Format - Task Name Context (context_chain.json) ⭐

**Purpose**: Verify modern task-name context format with multi-task dependencies

```bash
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "gemini_context_chain_test",
    "inputs": {
      "llm_model": "gemini-2.5-flash",
      "topic": "Artificial Intelligence in Healthcare"
    },
    "crew": '$(cat tests/test_crews/context_chain.json | jq -c .)'
  }' | jq .
```

**Or using file directly**:
```bash
# Create complete request file
cat > /tmp/test_context_chain.json <<'EOF'
{
  "name": "gemini_context_chain_test",
  "inputs": {
    "llm_model": "gemini-2.5-flash",
    "topic": "Artificial Intelligence in Healthcare"
  },
  "crew": <PASTE CONTENT FROM tests/test_crews/context_chain.json>
}
EOF

curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @/tmp/test_context_chain.json | jq .
```

**Expected Logs**:
```
INFO: Building 3 tasks (pass 1: creation)
DEBUG: Created task 0: 'research_task' (agent: researcher)
DEBUG: Created task 1: 'writing_task' (agent: writer)
DEBUG: Created task 2: 'editing_task' (agent: editor)
INFO: Resolving task context chains (pass 2)
DEBUG: Task 'research_task': no context (first task)
DEBUG: Task 'writing_task' → context task: 'research_task' ✓
INFO: Task 'writing_task' context resolved: ['research_task']
DEBUG: Task 'editing_task' → context task: 'research_task' ✓
DEBUG: Task 'editing_task' → context task: 'writing_task' ✓
INFO: Task 'editing_task' context resolved: ['research_task', 'writing_task']
INFO: ✓ Built 3 tasks with context resolution complete
```

**Validation**:
- ✅ Research task has no context
- ✅ Writing task gets research findings as context
- ✅ Editing task gets BOTH research AND article as context
- ✅ Final output is polished article that builds on all previous work

---

### Test 4: Auto-Chaining (No Context Field)

**Purpose**: Verify automatic sequential task chaining when no context specified

```bash
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "auto_chain_test",
    "inputs": {
      "llm_model": "gemini-2.5-flash",
      "topic": "Quantum Computing"
    },
    "crew": {
      "$schema": "urn:sd:schema.icrew.crew.2",
      "name": "auto_chain_crew",
      "process": "sequential",
      "agents": [
        {
          "name": "researcher",
          "role": "Researcher",
          "goal": "Research {topic}",
          "backstory": "Expert researcher"
        },
        {
          "name": "summarizer",
          "role": "Summarizer",
          "goal": "Summarize findings",
          "backstory": "Expert at synthesis"
        }
      ],
      "tasks": [
        {
          "description": "Research {topic}",
          "expected_output": "Research findings",
          "agent": "researcher"
        },
        {
          "description": "Summarize the research",
          "expected_output": "Summary",
          "agent": "summarizer"
        }
      ]
    }
  }' | jq .
```

**Note**: No `context` field in tasks! They should auto-chain.

**Expected Logs**:
```
INFO: Building 2 tasks (pass 1: creation)
DEBUG: Auto-generated task name: researcher_task_0
DEBUG: Auto-generated task name: summarizer_task_1
INFO: Resolving task context chains (pass 2)
DEBUG: Task 'researcher_task_0': no context (first task)
DEBUG: Task 'summarizer_task_1': auto-chained to previous task 'researcher_task_0'
```

**Validation**:
- ✅ Tasks created with auto-generated names
- ✅ Second task automatically gets first task's output as context
- ✅ Works like standard CrewAI sequential process

---

### Test 5: Artifact Download + File Processing

**Purpose**: Test artifact lifecycle and file tools

```bash
# First, upload test artifact to IVCAP
echo "Sample research data for processing" > /tmp/test_data.txt
ARTIFACT_URN=$(ivcap artifact upload /tmp/test_data.txt)

# Now test with that artifact
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "artifact_test",
    "artifact-urns": ["'$ARTIFACT_URN'"],
    "inputs": {
      "llm_model": "gemini-2.5-flash"
    },
    "crew": {
      "$schema": "urn:sd:schema.icrew.crew.2",
      "name": "file_processor",
      "process": "sequential",
      "agents": [{
        "name": "processor",
        "role": "File Processor",
        "goal": "Process files from artifacts directory",
        "backstory": "Expert at file analysis",
        "tools": [
          {"id": "urn:sd-core:crewai.builtin.directoryReadTool"},
          {"id": "urn:sd-core:crewai.builtin.fileReadTool"}
        ]
      }],
      "tasks": [{
        "name": "process_files",
        "description": "List and analyze all files in {inputs_directory}",
        "expected_output": "Summary of files analyzed",
        "agent": "processor"
      }]
    }
  }' | jq .
```

**Expected Logs**:
```
INFO: Downloading 1 artifacts...
INFO: Created inputs directory: runs/urn:ivcap:job:xyz/inputs
INFO: Downloading artifact: urn:ivcap:artifact:abc123
INFO: Downloaded urn:ivcap:artifact:abc123 → runs/urn:ivcap:job:xyz/inputs/test_data.txt
INFO: Downloaded 1/1 artifacts
INFO: ✓ Artifacts available at: runs/urn:ivcap:job:xyz/inputs
...
INFO: Cleaned up artifacts for job urn:ivcap:job:xyz
```

**Validation**:
- ✅ Artifact downloaded to job-specific inputs directory
- ✅ `inputs_directory` path injected into crew inputs
- ✅ DirectoryReadTool/FileReadTool can access files
- ✅ Directory cleaned up after execution
- ✅ No `runs/` directory remains after job

---

### Test 6: Per-Agent Custom Models (Mixed Gemini)

**Purpose**: Verify different agents can use different models

```bash
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "multi_model_test",
    "inputs": {"topic": "AI Ethics"},
    "crew": {
      "$schema": "urn:sd:schema.icrew.crew.2",
      "name": "multi_model_crew",
      "process": "sequential",
      "agents": [
        {
          "name": "fast_researcher",
          "role": "Quick Researcher",
          "goal": "Quickly research {topic}",
          "backstory": "Fast and efficient researcher",
          "llm": "gemini-2.0-flash-exp",
          "tools": [{"id": "urn:sd-core:crewai.builtin.websiteSearchTool"}]
        },
        {
          "name": "deep_analyzer",
          "role": "Deep Analyst",
          "goal": "Deeply analyze research on {topic}",
          "backstory": "Thorough and comprehensive analyst",
          "llm": "gemini-2.5-flash"
        }
      ],
      "tasks": [
        {
          "name": "research",
          "description": "Quick research on {topic}",
          "expected_output": "Research summary",
          "agent": "fast_researcher"
        },
        {
          "name": "analysis",
          "description": "Deep analysis of the research",
          "expected_output": "Detailed analysis",
          "agent": "deep_analyzer",
          "context": ["research"]
        }
      ]
    }
  }' | jq .
```

**Expected Logs**:
```
INFO: Creating LLM with LiteLLM proxy + JWT: gemini-2.5-flash
INFO: ✓ LLM created: gemini-2.5-flash via proxy with JWT
INFO: Built 2 agents
INFO: Creating LLM with LiteLLM proxy + JWT: gemini-2.0-flash-exp
INFO: ✓ LLM created: gemini-2.0-flash-exp via proxy with JWT
INFO: Creating LLM with LiteLLM proxy + JWT: gemini-2.5-flash
INFO: ✓ LLM created: gemini-2.5-flash via proxy with JWT
```

**Validation**:
- ✅ Fast researcher uses gemini-2.0-flash-exp
- ✅ Deep analyzer uses gemini-2.5-flash
- ✅ Both authenticated with same JWT
- ✅ Analysis task receives research context

---

### Test 7: All Features Combined ⭐

**Purpose**: Comprehensive test of all features together

```bash
# Upload test artifact
echo "Background research document" > /tmp/background.txt
ARTIFACT_URN=$(ivcap artifact upload /tmp/background.txt)

# Run comprehensive test
curl -X POST http://localhost:8077 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d '{
    "name": "comprehensive_test",
    "artifact-urns": ["'$ARTIFACT_URN'"],
    "inputs": {
      "topic": "AI Governance"
    },
    "crew": {
      "$schema": "urn:sd:schema.icrew.crew.2",
      "name": "comprehensive_crew",
      "process": "sequential",
      "verbose": true,
      "agents": [
        {
          "name": "background_reader",
          "role": "Background Researcher",
          "goal": "Read background materials",
          "backstory": "Expert at processing documents",
          "llm": "gemini-2.0-flash-exp",
          "tools": [{"id": "urn:sd-core:crewai.builtin.fileReadTool"}]
        },
        {
          "name": "web_researcher",
          "role": "Web Researcher",
          "goal": "Research {topic} online",
          "backstory": "Expert at web research",
          "llm": "gemini-2.5-flash",
          "tools": [{"id": "urn:sd-core:crewai.builtin.websiteSearchTool"}]
        },
        {
          "name": "synthesizer",
          "role": "Synthesis Expert",
          "goal": "Synthesize all findings",
          "backstory": "Expert at combining multiple sources",
          "llm": "gemini-2.5-flash"
        }
      ],
      "tasks": [
        {
          "name": "read_background",
          "description": "Read all files in {inputs_directory}",
          "expected_output": "Summary of background materials",
          "agent": "background_reader",
          "context": []
        },
        {
          "name": "web_research",
          "description": "Research {topic} using web search",
          "expected_output": "Web research findings",
          "agent": "web_researcher",
          "context": []
        },
        {
          "name": "synthesize",
          "description": "Synthesize background materials and web research",
          "expected_output": "Comprehensive synthesis",
          "agent": "synthesizer",
          "context": ["read_background", "web_research"]
        }
      ]
    }
  }' | jq .
```

**Features Tested**:
- ✅ Artifact download and cleanup
- ✅ JWT authentication
- ✅ Per-agent custom models (2.0-flash-exp vs 2.5-flash)
- ✅ Task context with multiple dependencies
- ✅ File tools (DirectoryReadTool, FileReadTool)
- ✅ Web tools (WebsiteSearchTool)

**Expected Logs**:
```
INFO: JWT token detected → using LiteLLM proxy authentication
INFO: Downloading 1 artifacts...
INFO: Downloaded urn:ivcap:artifact:... → runs/.../inputs/background.txt
INFO: ✓ Artifacts available at: runs/.../inputs
INFO: Loaded crew definition: comprehensive_crew
INFO: ✓ LLM created: gemini-2.5-flash via proxy with JWT (crew default)
INFO: Built 3 agents
INFO: Building 3 tasks (pass 1: creation)
INFO: Resolving task context chains (pass 2)
DEBUG: Task 'read_background': no context (first task)
DEBUG: Task 'web_research': no context (first task)
DEBUG: Task 'synthesize' → context task: 'read_background' ✓
DEBUG: Task 'synthesize' → context task: 'web_research' ✓
INFO: Task 'synthesize' context resolved: ['read_background', 'web_research']
INFO: ✓ Crew built: 3 agents, 3 tasks
INFO: Executing crew: comprehensive_test
INFO: ✓ Crew execution complete
INFO: Cleaned up artifacts for job ...
```

---

## 🔍 Debugging & Monitoring

### View Logs in Real-Time

```bash
# Terminal 1: Start service with verbose logging
CREWAI_VERBOSE=true poetry ivcap run

# Terminal 2: Monitor specific log patterns
tail -f service.log | grep -E "(context:|LLM created|Downloaded|Cleaned)"
```

### Check Task Context Resolution

```bash
# Filter for context-related logs
tail -f service.log | grep "context"

# Expected patterns:
# "Task 'X' → context task: 'Y' ✓"           (new format)
# "Task 'X' → context agent: 'Y' ... [LEGACY FORMAT]"  (legacy)
# "Task 'X': auto-chained to previous task 'Y'"  (auto-chain)
```

### Monitor Artifact Lifecycle

```bash
tail -f service.log | grep -E "(Download|Cleanup|inputs)"

# Expected flow:
# "Downloading N artifacts..."
# "Created inputs directory: runs/{job_id}/inputs"
# "Downloaded urn:... → runs/{job_id}/inputs/file.txt"
# "✓ Artifacts available at: runs/{job_id}/inputs"
# ... (crew execution) ...
# "Cleaned up artifacts for job {job_id}"
```

### Verify Authentication Flow

```bash
tail -f service.log | grep -E "(JWT|LLM created)"

# With JWT:
# "JWT token detected → using LiteLLM proxy authentication"
# "✓ LLM created: gemini-2.5-flash via proxy with JWT"

# Without JWT:
# "No JWT token → using fallback authentication"
# "✓ LLM created: gemini-2.5-flash via proxy without JWT"
```

---

## 📊 Response Structure

All successful responses follow this schema:

```json
{
  "$schema": "urn:sd-core:schema.crewai.response.1",
  "answer": "Final crew output (string)",
  "crew_name": "Name of executed crew",
  "place_holders": [],
  "task_responses": [
    {
      "agent": "researcher",
      "description": "Task description",
      "summary": "Task summary",
      "raw": "Full task output"
    }
  ],
  "created_at": "2025-11-05T10:30:00+00:00",
  "process_time_sec": 12.34,
  "run_time_sec": 45.67,
  "token_usage": {
    "total_tokens": 5000,
    "prompt_tokens": 2000,
    "completion_tokens": 3000,
    "successful_requests": 10
  },
  "citations": null
}
```

### Extract Specific Fields

```bash
# Get final answer only
curl ... | jq -r '.answer'

# Get token usage
curl ... | jq '.token_usage'

# Get individual task outputs
curl ... | jq '.task_responses[] | {agent, summary}'

# Check execution time
curl ... | jq '{process_time_sec, run_time_sec}'
```

---

## ⚠️ Common Issues & Solutions

### Issue 1: "No valid LLM configuration"

**Error**:
```json
{
  "detail": "No valid LLM configuration available. Please set:\n  1. LITELLM_PROXY_URL..."
}
```

**Solutions**:
```bash
# Check environment
echo $LITELLM_PROXY_URL
echo $OPENAI_API_KEY

# Set proxy URL
export LITELLM_PROXY_URL="https://litellm-proxy.ivcap.net"

# Or use OpenAI fallback for testing
export OPENAI_API_KEY="sk-proj-..."
```

### Issue 2: "Unknown agent 'X'"

**Error**: "Unknown agent 'writer'. Available agents: ['researcher']"

**Solution**: Check agent names match exactly in tasks
```json
{
  "agents": [{"name": "researcher", ...}],
  "tasks": [
    {"agent": "researcher"}  // ✓ Correct
    // {"agent": "writer"}   // ✗ Not defined in agents
  ]
}
```

### Issue 3: "Task references unknown context"

**Warning**: "Task 'write_task' references unknown context 'research_task_wrong'"

**Solution**: Verify task names or use agent names for legacy format
```json
{
  "tasks": [
    {"name": "research_task", ...},
    {"name": "write_task", "context": ["research_task"]}  // ✓ Name matches
    // {"name": "write_task", "context": ["research_task_wrong"]}  // ✗ Typo
  ]
}
```

### Issue 4: Artifacts Not Found

**Error**: "Failed to download urn:ivcap:artifact:..."

**Solutions**:
```bash
# Verify artifact exists
ivcap artifact get urn:ivcap:artifact:abc123

# Check IVCAP token has access
echo $IVCAP_TOKEN

# Check IVCAP_BASE_URL is correct
echo $IVCAP_BASE_URL
```

### Issue 5: No Task Context Being Passed

**Symptom**: Tasks don't seem to build on each other

**Debug**:
```bash
# Check logs for context resolution
tail -f service.log | grep "context resolved"

# Should see:
# "Task 'write_task' context resolved: ['research_task']"

# If not, check:
# 1. Are task names spelled correctly in context array?
# 2. Is crew process set to "sequential"?
# 3. Are you using legacy agent-name format correctly?
```

---

## 📈 Performance Monitoring

### Check Token Usage

```bash
# Get token stats from response
curl ... | jq '{
  total_tokens: .token_usage.total_tokens,
  prompt_tokens: .token_usage.prompt_tokens,
  completion_tokens: .token_usage.completion_tokens,
  cost_estimate: (.token_usage.total_tokens * 0.00001)
}'
```

### Measure Execution Time

```bash
# Time the entire request
time curl -X POST http://localhost:8077 \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @tests/test_crews/context_chain.json | jq .

# Extract timing from response
curl ... | jq '{
  cpu_time: .process_time_sec,
  wall_time: .run_time_sec,
  efficiency: (.process_time_sec / .run_time_sec)
}'
```

### Monitor Resource Usage

```bash
# Monitor service memory/CPU
watch -n 2 'ps aux | grep "python.*service.py" | grep -v grep'

# Check disk usage (runs directory)
du -sh runs/

# Should be empty after jobs complete (cleanup working)
```

---

## 🎯 Quick Reference Commands

### Standard Test (Gemini 2.5 Flash)

```bash
export IVCAP_TOKEN=$(ivcap context get-token)

curl -X POST http://localhost:8077 \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/simple_crew2.json | jq .
```

### Test with Model Override

```bash
curl -X POST http://localhost:8077 \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test",
    "inputs": {"llm_model": "gemini-2.0-flash-exp"},
    "crew": <CREW_DEFINITION>
  }' | jq .
```

### Test with Artifacts

```bash
curl -X POST http://localhost:8077 \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test",
    "artifact-urns": ["urn:ivcap:artifact:YOUR_URN"],
    "inputs": {},
    "crew": <CREW_DEFINITION>
  }' | jq .
```

### Save Response for Analysis

```bash
curl ... | tee /tmp/crew_response.json | jq '.answer'

# Later analyze full response
jq . /tmp/crew_response.json
```

---

## 📚 Task Context Format (Standard CrewAI)

The service follows **standard CrewAI behavior** for task context:

| Format | Example | Behavior |
|--------|---------|----------|
| **Empty array** | `"context": []` | No context (first task) |
| **Omit field** | (no context field) | Auto-chain to previous task |
| **Task name** | `"context": ["research_task"]` | Explicit task reference |
| **Multiple tasks** | `"context": ["task1", "task2"]` | Multi-task dependencies |

### Standard Format (CrewAI-compliant)

```json
{
  "tasks": [
    {
      "name": "research_task",
      "agent": "researcher",
      "description": "Research the topic",
      "expected_output": "Research findings"
    },
    {
      "name": "write_task",
      "agent": "writer",
      "description": "Write article based on research",
      "expected_output": "Article draft",
      "context": ["research_task"]
    }
  ]
}
```

**Key Points**:
- ✅ Tasks must have explicit names
- ✅ Context references task names (not agent names)
- ✅ First task typically has no context
- ✅ Sequential tasks auto-chain if context omitted

---

## 📦 Example Test Files Reference

All test files are located in `examples/` directory. Each demonstrates different service capabilities.

### Test 1: `simple_crew2_request.json` - Basic Workflow

**Purpose**: Test basic sequential workflow with web research and writing  
**Features**: SerperDevTool, WebsiteSearchTool, task chaining, anti-hallucination prompting  
**Agents**: researcher, writer  
**Tasks**: 2 (research → write)

```bash
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/simple_crew2_request.json | jq .
```

**What's tested:**
- Basic crew execution
- Web search tools (SerperDevTool + WebsiteSearchTool)
- Sequential task chaining
- Anti-hallucination instructions
- Source citation requirements

**Expected outcome**: Blog post about AI advancements with timeline and citations

---

### Test 2: `crew3_request.json` - Anti-Hallucination Research

**Purpose**: Test comprehensive anti-hallucination safeguards  
**Features**: Extensive source verification, explicit gap acknowledgment  
**Agents**: researcher (technical), synthesizer (writer)  
**Tasks**: 2 (research AI releases → write article)

```bash
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/crew3_request.json | jq .
```

**What's tested:**
- Anti-hallucination prompting techniques
- Confidence level tracking (Verified/Likely/Uncertain)
- Explicit information gap reporting
- Source quality assessment
- Complex search strategies

**Expected outcome**: Research findings with explicit confidence levels and gap acknowledgment

---

### Test 3: `document_reader_request.json` - Artifact Processing

**Purpose**: Test artifact download and PDF document processing  
**Features**: artifact-urns, PDFSearchTool auto-injection, DirectoryReadTool  
**Agents**: extractor, synthesizer  
**Tasks**: 2 (extract from PDFs → synthesize)  
**Artifacts**: 2 PDF files (faw1.pdf, faw2.pdf)

```bash
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/document_reader_request.json | jq .
```

**What's tested:**
- Artifact download from IVCAP
- PDF file detection and auto-injection of PDFSearchTool
- DirectoryReadTool for file listing
- PDFSearchTool for semantic search within PDFs
- Document synthesis across multiple files
- Artifact cleanup after execution

**Expected outcome**: Synthesized summary combining insights from both PDF documents

**Key logs to watch for:**
```
INFO: Downloading 2 artifacts...
INFO: Downloaded urn:ivcap:artifact:... → runs/.../inputs/faw1.pdf
INFO: Downloaded urn:ivcap:artifact:... → runs/.../inputs/faw2.pdf
INFO: 📄 Detected 2 PDF file(s) - PDFSearchTool recommended
INFO: → Auto-injected PDFSearchTool into agent 'extractor' for 2 PDF(s)
INFO: Cleaned up artifacts for job ...
```

---

### Test 4: `knowledge_request.json` - Knowledge Sources ⭐ NEW

**Purpose**: Test additional-inputs field with previous crew outputs as knowledge  
**Features**: knowledge_sources, StringKnowledgeSource, crew-level RAG, multi-stage workflows  
**Agents**: research_analyst, synthesis_writer  
**Tasks**: 2 (analyze with context → synthesize report)  
**Knowledge Sources**: 2 markdown documents (AI Safety research + Expert profiles)

```bash
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @examples/knowledge_request.json | jq .
```

**What's tested:**
- `additional-inputs` field (new feature)
- Automatic conversion to StringKnowledgeSource
- Crew-level knowledge sharing (all agents get access)
- JWT-authenticated embedder for knowledge embedding
- Semantic search across previous research
- Multi-stage research workflows

**Expected outcome**: Analysis that references and builds upon previous research findings

**Key logs to watch for:**
```
INFO: 📚 Processing additional inputs as knowledge sources...
INFO: Processing 2 additional input(s) into knowledge sources
INFO: ✓ Created knowledge source 1: 1401 chars, 183 words
INFO: ✓ Created knowledge source 2: 1700 chars, 218 words
INFO: ✓ Created 2 knowledge source(s) for crew
INFO:   Knowledge sources will use JWT-authenticated embedder
INFO: ✓ Added 2 knowledge source(s) to crew
```

**Validation checks:**
- ✅ Knowledge sources created from additional-inputs
- ✅ Embeddings created via JWT-authenticated embedder
- ✅ Agents can query knowledge (look for references to previous research in output)
- ✅ No errors during knowledge initialization

---

### Summary Table: All Examples

| File | Purpose | Features Tested | Artifacts | Knowledge | Complexity |
|------|---------|----------------|-----------|-----------|------------|
| `simple_crew2_request.json` | Basic workflow | Web search, task chaining | No | No | Low |
| `crew3_request.json` | Anti-hallucination | Source verification, gap reporting | No | No | Medium |
| `document_reader_request.json` | PDF processing | Artifact download, PDFSearchTool | 2 PDFs | No | Medium |
| `knowledge_request.json` | Multi-stage workflow | Knowledge sources, RAG | No | 2 sources | High |
| `software_discovery_aspect_test.json` | Crew aspect reference | Entity URN, ML tool discovery | No | No | Medium |
| `software_discovery_data_analysis.json` | Domain-specific discovery | Bioinformatics tools | No | No | Medium |

### Quick Test All Examples

```bash
# Test basic workflow
curl -X POST http://localhost:8077/ \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/simple_crew2_request.json | jq -r '.answer' > /tmp/test1.md

# Test anti-hallucination
curl -X POST http://localhost:8077/ \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/crew3_request.json | jq -r '.answer' > /tmp/test2.md

# Test document processing
curl -X POST http://localhost:8077/ \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/document_reader_request.json | jq -r '.answer' > /tmp/test3.md

# Test knowledge sources
curl -X POST http://localhost:8077/ \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/knowledge_request.json | jq -r '.answer' > /tmp/test4.md

# Verify all outputs created
ls -lh /tmp/test*.md
```

---

## 🔬 Advanced Testing

### Test Async Task Execution

```json
{
  "tasks": [
    {
      "name": "research_ai",
      "agent": "researcher",
      "async_execution": true
    },
    {
      "name": "research_ml",
      "agent": "researcher",
      "async_execution": true
    },
    {
      "name": "write_article",
      "agent": "writer",
      "context": ["research_ai", "research_ml"]  // Waits for both async tasks
    }
  ]
}
```

### Test Complex Context Chains

```json
{
  "tasks": [
    {"name": "task_a", "context": []},
    {"name": "task_b", "context": []},
    {"name": "task_c", "context": ["task_a"]},
    {"name": "task_d", "context": ["task_a", "task_b"]},
    {"name": "task_e", "context": ["task_c", "task_d"]}
  ]
}
```

---

## 📞 Support & Troubleshooting

### Enable Debug Logging

```bash
# Set Python logging to DEBUG
export PYTHONUNBUFFERED=1
poetry ivcap run --verbose

# Or modify logging.json
```

### Check CrewBuilder Logs

```bash
tail -f service.log | grep "app.crew_builder"

# Shows:
# - Task creation
# - Context resolution
# - Warnings for unknown references
```

### Validate Request Schema

```bash
# Pretty-print your request before sending
cat /tmp/my_request.json | jq .

# Check for required fields
cat /tmp/my_request.json | jq 'has("name") and has("crew")'
```

### Contact Support

If issues persist:
1. Capture full logs: `poetry ivcap run 2>&1 | tee debug.log`
2. Save failing request: `cat failing_request.json`
3. Note error message and timestamp
4. Check IVCAP platform status

---

### Test 5: `software_discovery_aspect_test.json` - Crew Aspect Reference ⭐ NEW

**Purpose**: Test using crew-ref with entity URN (not inline crew definition)  
**Features**: Aspect loading from IVCAP, entity URN resolution, multi-agent workflow  
**Agents**: discovery_agent, analysis_agent, synthesis_agent  
**Tasks**: 3 (discover tools → analyze candidates → recommend top tools)

```bash
# Test ML training infrastructure discovery
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @tests/software_discovery_aspect_test.json | jq .

# Test bioinformatics tools discovery
curl -X POST http://localhost:8077/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -d @tests/software_discovery_data_analysis.json | jq .
```

**What's tested:**
- Loading crew from IVCAP aspect using `crew-ref`
- Entity URN resolution (not artifact URN)
- Complex placeholder usage (research_topic, keywords, additional_information)
- Three-stage discovery workflow
- Web research with SerperDevTool and WebsiteSearchTool
- Multi-agent collaboration

**Request structure:**
```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Software Discovery Test",
  "crew-ref": "urn:sd:crewai:crew.software_discovery",
  "inputs": {
    "research_topic": "Deep Learning Training Infrastructure",
    "keywords": "PyTorch, distributed training, GPU clusters",
    "additional_information": "Multi-node training, 1B+ parameters, $10k budget"
  }
}
```

**Expected outcome**: 
- Discovery report with 10-15 relevant tools
- Detailed analysis of top 5-10 candidates
- Final recommendations for top 3-5 tools with comparison table

**Key logs to watch for:**
```
INFO: Loaded crew definition: Software Discovery
INFO: Building crew: Software Discovery
INFO: Built 3 agents
INFO: Building 3 tasks (pass 1: creation)
INFO: Resolving task context chains (pass 2)
INFO: Task 'Analysis Task' context resolved: ['Discovery Task']
INFO: Task 'Synthesis Task' context resolved: ['Analysis Task']
INFO: ✓ Crew built: 3 agents, 3 tasks
```

**Validation checks:**
- ✅ Crew loaded from IVCAP aspect (not inline definition)
- ✅ Entity URN `urn:sd:crewai:crew.software_discovery` resolves correctly
- ✅ All three placeholders populated in agent goals and task descriptions
- ✅ Three tasks execute sequentially with proper context chaining
- ✅ Final output includes tool recommendations with rationale

**Using the helper script** (recommended):
```bash
# Create IVCAP order using helper script
tests/create_order.sh tests/software_discovery_aspect_test.json

# Returns job ID and monitoring commands
```

**Alternative: Using Makefile for IVCAP orders**:
```bash
# Create order on deployed IVCAP service
make test-job-ivcap TEST_REQUEST=tests/software_discovery_aspect_test.json
```

**See detailed documentation**: [tests/README_SOFTWARE_DISCOVERY.md](tests/README_SOFTWARE_DISCOVERY.md)

---

## 🎉 Success Indicators

Your implementation is working correctly if:

- ✅ Legacy crews (simple_crew2.json) execute without modification
- ✅ New crews (context_chain.json) show proper task chaining
- ✅ Logs show "context resolved: ['task1', 'task2']"
- ✅ Artifacts download and cleanup automatically
- ✅ JWT authentication shows in logs
- ✅ Per-agent models use different Gemini variants
- ✅ No "runs/" directory exists after job completion
- ✅ Response contains complete task outputs
- ✅ Token usage tracked accurately

---

**Last Updated**: Implementation of task context chaining feature  
**Service Version**: 0.2.0  
**Default Model**: gemini-2.5-flash

