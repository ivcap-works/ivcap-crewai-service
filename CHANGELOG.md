# Changelog

All notable changes to the IVCAP CrewAI Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - 2025-01-13

### ⚠️ BREAKING CHANGES

This release introduces significant changes to the request format that require frontend/client updates.

#### Request Format Change

The service has moved from a parameter-array format to a structured JSON request body format.

##### OLD FORMAT (v0.1.x) - NO LONGER SUPPORTED

```json
{
  "service": "urn:ivcap:service:01555c28-32d0-5839-b92b-f3e52410d6dd",
  "parameters": [
    { "name": "crew", "value": "urn:ivcap:aspect:crew-definition-123" },
    { "name": "p1", "value": "keywords:AI, machine learning" },
    { "name": "p2", "value": "research_topic:Quantum Computing" },
    { "name": "p3", "value": "additional_information:Focus on 2024-2025" }
  ]
}
```

##### NEW FORMAT (v0.2.0) - REQUIRED

The request body is now a single JSON parameter:

```json
{
  "service": "urn:ivcap:service:01555c28-32d0-5839-b92b-f3e52410d6dd",
  "parameters": [
    {
      "name": "body",
      "value": "<JSON string - see expanded view below>"
    }
  ]
}
```

Expanded view of the request body value:

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Research Job",
  "crew-ref": "urn:ivcap:aspect:crew-definition-123",
  "inputs": {
    "research_topic": "Quantum Computing",
    "keywords": "AI, machine learning",
    "additional_information": "Focus on 2024-2025",
    "llm_model": "gpt-4o"
  }
}
```

#### Why This Change?

The new format provides:

1. **Clean separation** between inputs (placeholder values) and knowledge context (previous crew outputs)
2. **Better structure** for complex features like artifact uploads and knowledge sources
3. **Standards compliance** with IVCAP schema versioning
4. **Extensibility** for future features without breaking existing clients
5. **Type safety** via proper JSON schema validation

---

### Added

#### 1. Knowledge Sources (additional-inputs)

Pass previous crew outputs as searchable knowledge using RAG (Retrieval-Augmented Generation).

**Use Case:** Chain crews together where output from Crew A becomes searchable knowledge for Crew B.

**Example:**

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Synthesis with Context",
  "crew-ref": "urn:ivcap:aspect:analysis-crew",
  "inputs": {
    "topic": "AI Safety Alignment"
  },
  "additional-inputs": [
    "# Deep Research Output\n\nKey findings from comprehensive research...",
    "# Expert Profiles\n\nLeading researchers in the field..."
  ]
}
```

**Features:**

- Accepts single string or array of strings (markdown format)
- Automatically converted to CrewAI StringKnowledgeSource objects
- Embedded using JWT-authenticated embedder via LiteLLM proxy
- Stored in job-specific ChromaDB for semantic search
- Available to all agents in the crew automatically via RAG
- Complete job isolation - no cross-contamination between runs

**Agent Access:**

- No explicit tool configuration needed
- Agents can naturally reference "previous research" in conversations
- CrewAI automatically retrieves relevant context from knowledge sources
- Semantic search ensures only relevant information is surfaced

**Implementation:**

- Added `knowledge_processor.py` module
- Added `additional_inputs` field to CrewRequest model
- Integrated into crew building pipeline (service.py:466-480)
- Test coverage in tests/test_knowledge_integration.py

#### 2. Structured Request Body Schema

**New Schema Identifier:** `urn:sd-core:schema.crewai.request.1`

**Complete Request Structure:**

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Job Name",
  "crew-ref": "urn:ivcap:aspect:...",
  "inputs": {
    "research_topic": "string",
    "keywords": "string",
    "additional_information": "string",
    "llm_model": "string"
  },
  "artifact-urns": ["urn:ivcap:artifact:..."],
  "additional-inputs": ["string"],
  "enable-citations": false
}
```

**Field Descriptions:**

- `$schema` (required): Schema version identifier
- `name` (required): Human-readable job name
- `crew-ref` (optional): URN reference to crew definition stored in IVCAP
- `crew` (optional): Inline crew definition (mutually exclusive with crew-ref)
- `inputs` (optional): Dictionary of placeholder values
  - `llm_model`: Override default LLM model for this execution
  - Other keys match crew's placeholders array
- `artifact-urns` (optional): Array of IVCAP artifact URNs to download
- `additional-inputs` (optional): Previous crew outputs for RAG search
- `enable-citations` (optional): Enable citation tracking (experimental)

#### 3. LLM Model Override

Override the default LLM model at runtime via `inputs.llm_model`:

```json
{
  "inputs": {
    "research_topic": "Quantum Machine Learning",
    "llm_model": "gpt-4o"
  }
}
```

#### 4. Enhanced Backend Architecture

**CrewBuilder with Task Context Resolution:**

- Two-pass task building for proper context chaining
- Resolves task context references (string names to Task objects)
- Enables sequential task execution with proper output passing
- Implementation: crew_builder.py

**Knowledge Processor:**

- Converts markdown strings to CrewAI knowledge sources
- Handles both single string and array inputs
- Adds metadata for tracking and debugging
- Implementation: knowledge_processor.py

**Job-Isolated Storage:**

- Each job gets its own CREWAI_STORAGE_DIR: `runs/{job_id}`
- Prevents RAG/memory/knowledge cross-contamination
- Automatic cleanup after execution
- Set in service.py:336-342

**JWT-Authenticated Embeddings:**

- Knowledge sources use same JWT-authenticated embedder as crew
- Configured via LiteLLM proxy for consistent authentication

**Automatic Tool Injection:**

- PDFSearchTool auto-injected when PDF artifacts detected
- DirectorySearchTool auto-injected when text files detected
- Implementation: service.py:386-436

**Enhanced Logging:**

- Diagnostic logging for embedder configuration
- RAG tools status reporting
- Knowledge source creation tracking
- JWT token detection logging

#### 5. Task Output Files

Individual task outputs and final crew output saved to files:

- Task outputs: `runs/{job_id}/outputs/01_task_name.md`
- Final output: `runs/{job_id}/outputs/final_output.md`
- Implementation: service.py:517-555

---

### Changed

#### Request Processing Flow

**Old Flow (v0.1.x):**

1. Extract parameters from array (p1, p2, p3)
2. Parse colon-prefixed values
3. Create crew
4. Execute

**New Flow (v0.2.0):**

1. Parse structured JSON request body
2. Validate against schema
3. Extract JWT token from JobContext
4. Download artifacts (if specified)
5. Process additional-inputs into knowledge sources
6. Create authenticated LLM instances
7. Build crew with proper task context resolution
8. Execute crew with knowledge sources
9. Save task outputs to files
10. Return structured response

#### Crew Building Process

- Now uses CrewBuilder class for proper task context resolution
- Two-pass building: create all tasks first, then resolve context references
- Supports knowledge sources parameter
- Supports embedder configuration parameter
- Implementation: crew_builder.py:184-274

#### Authentication Flow

- JWT token extraction improved with 4-path fallback
- Primary path: job_ctxt.job_authorization (ivcap-ai-tool v0.7.17+)
- Token passed to both main LLM and planning LLM
- Token used for embedder configuration
- Implementation: service.py:173-213

---

### Deprecated

#### Parameter Names (Removed in v0.2.0)

- ❌ `p1` - No longer accepted
- ❌ `p2` - No longer accepted  
- ❌ `p3` - No longer accepted
- ❌ `crew` as a parameter - Now must be `crew-ref` in request body or inline `crew` object

#### Value Format (Removed in v0.2.0)

- ❌ Colon-prefix format: `"keywords:value"` - No longer parsed
- ❌ Colon-prefix format: `"research_topic:value"` - No longer parsed
- ❌ Colon-prefix format: `"additional_information:value"` - No longer parsed

**Migration:** Remove prefixes and use clean key-value pairs in inputs dictionary.

---

### Migration Guide for Frontend Teams

#### Overview

The migration requires updating how requests are constructed and sent to the CrewAI service. The main changes are:

1. Parameter names: `p1`, `p2`, `p3` → structured `inputs` dictionary
2. Value format: Remove colon prefixes (`keywords:`, `research_topic:`)
3. Previous outputs: Move from `additional_information` to `additional-inputs`
4. Request structure: Wrap everything in a JSON request body

#### Step 1: Update Request Structure

**Before (v0.1.x):**

```typescript
const parameters = [
  { name: 'crew', value: crewAspect.content.artifact },
  { name: 'p1', value: `keywords:${keywords}` },
  { name: 'p2', value: `research_topic:${prompt}` },
  { name: 'p3', value: `additional_information:${inputContent}` },
  { name: 'openai-model', value: 'gpt-4.1' },
];
```

**After (v0.2.0):**

```typescript
const requestBody = {
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": `${crewAspect.content.name} - ${prompt.substring(0, 10)}`,
  "crew-ref": crewAspect.content.artifact,
  "inputs": {
    "research_topic": prompt,
    "keywords": keywords,
    "additional_information": "",
    "llm_model": "gpt-4o"
  }
};

const parameters = [
  {
    name: "body",
    value: JSON.stringify(requestBody)
  }
];
```

#### Step 2: Handle Previous Crew Outputs

**Before (v0.1.x):**

Previous outputs were concatenated into the additional_information placeholder:

```typescript
const inputContent = previousOutputs.join('\n\n');
{ name: 'p3', value: `additional_information:${inputContent}` }
```

**After (v0.2.0):**

Use dedicated additional-inputs field with XML-wrapped outputs:

```typescript
// Format each previous node output with XML structure
const formattedInputs = inputs.map((input) => {
  const nodeName = input.data.label || 'Unknown Node';
  const nodePrompt = input.data.prompt || input.data.inputs || '';
  const nodeOutput = input.data.output || '';
  
  const escapeXml = (str: string) => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');
  };
  
  return `<crew name="${nodeName}" prompt="${escapeXml(nodePrompt)}">
${nodeOutput}
</crew>`;
});

const requestBody = {
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Job Name",
  "crew-ref": crewUrn,
  "inputs": {
    "research_topic": prompt,
    "keywords": "",
    "additional_information": ""
  }
};

// Add previous outputs as additional-inputs if they exist
if (formattedInputs.length > 0) {
  requestBody["additional-inputs"] = formattedInputs;
}
```

#### Step 3: Update TypeScript Types

Create or update type definitions:

```typescript
// File: app/src/types/crewai.ts
export interface CrewAIRequest {
  "$schema": "urn:sd-core:schema.crewai.request.1";
  name: string;
  "crew-ref"?: string;
  crew?: Record<string, any>;
  inputs?: {
    research_topic?: string;
    keywords?: string;
    additional_information?: string;
    llm_model?: string;
    [key: string]: any;
  };
  "artifact-urns"?: string[];
  "additional-inputs"?: string | string[];
  "enable-citations"?: boolean;
}
```

#### Step 4: Update Service Functions

**Before (v0.1.x):**

```typescript
export const createCrewOrder = async (
  crew: string,
  p1: string,
  p2: string,
  p3: string,
  token: string,
  config: IvcapConfig
) => {
  const parameters = [
    { name: "crew", value: crew },
    { name: "p1", value: p1 },
    { name: "p2", value: p2 },
    { name: "p3", value: p3 }
  ];
  // ...
};
```

**After (v0.2.0):**

```typescript
export const createCrewOrder = async (
  requestBody: CrewAIRequest,
  serviceUrn: string,
  projectUrn: string,
  token: string,
  config: IvcapConfig
) => {
  const orderPayload = {
    service: serviceUrn,
    parameters: [
      {
        name: "body",
        value: JSON.stringify(requestBody)
      }
    ]
  };
  
  const orderResponse = await createOrder(token, config, orderPayload);
  
  // Extract crew URN from request body
  const crewUrn = requestBody["crew-ref"];
  if (crewUrn) {
    await createCrewOrderAspect(
      orderResponse.id,
      projectUrn,
      serviceUrn,
      requestBody.name,
      crewUrn,
      token,
      config
    );
  }
  
  return orderResponse;
};
```

#### Step 5: Files to Modify

1. **app/src/utils/nodes/crewNode.ts**
   - Update request body construction (lines ~254-303)
   - Add XML formatting for previous outputs
   - Change createCrewOrder call signature

2. **app/src/services/ivcap/CrewAI.ts**
   - Update createCrewOrder function signature
   - Change from individual parameters to requestBody object

3. **app/src/types/crewai.ts** (create if doesn't exist)
   - Add CrewAIRequest interface
   - Export type definitions

4. **app/src/utils/nodes/toolNode.ts** (if applicable)
   - Apply similar XML formatting for tool outputs

#### Step 6: Testing the Migration

Test with simple crew:

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Test Migration",
  "crew-ref": "urn:ivcap:aspect:simple-crew",
  "inputs": {
    "research_topic": "Test Topic"
  }
}
```

Test with previous outputs:

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Test Knowledge",
  "crew-ref": "urn:ivcap:aspect:analysis-crew",
  "inputs": {
    "topic": "AI Safety"
  },
  "additional-inputs": [
    "# Previous Research\n\nKey findings..."
  ]
}
```

#### Step 7: Validation Checklist

- [ ] Request body structure matches schema
- [ ] `$schema` field is present with correct value
- [ ] `crew-ref` or `crew` is provided (not both)
- [ ] `inputs` dictionary uses clean key-value pairs (no colons)
- [ ] Previous outputs use `additional-inputs` field
- [ ] Request body is JSON.stringify'd as the body parameter value
- [ ] All placeholder names match crew definition
- [ ] LLM model override (if needed) is in `inputs.llm_model`

---

### Benefits of the New Format

1. **Semantic Clarity**: `additional-inputs` clearly indicates previous crew outputs for RAG, while `additional_information` remains a simple placeholder value

2. **RAG-Powered Knowledge**: Previous crew outputs are automatically embedded and searchable - much more powerful than string concatenation

3. **Better Structure**: Clean separation of concerns (inputs vs knowledge vs artifacts)

4. **Type Safety**: Proper JSON schema validation with better error messages

5. **Future-Proof**: Easy to add new fields without breaking changes

---

### Technical Details

#### Backend Changes

**Files Modified:**

- service.py: Added additional_inputs field, knowledge processing, enhanced logging
- service_types.py: Updated CrewRequest model with new fields
- crew_builder.py: Two-pass task context resolution, knowledge sources support
- llm_factory.py: Support for model override parameter

**Files Added:**

- knowledge_processor.py: Knowledge source creation and processing
- tests/test_knowledge_integration.py: Comprehensive knowledge sources tests
- tests/test_knowledge_processor.py: Unit tests for knowledge processor
- tests/test_knowledge_simple.py: Simple smoke tests

**Dependencies Updated:**

- crewai[tools] >=1.3.0,<2.0.0: Support for knowledge sources
- ivcap-ai-tool >=0.7.17,<0.8.0: JWT token from job_authorization attribute

#### Request Validation

The service validates:

- Schema identifier is correct
- Either crew-ref or crew is provided (not both)
- inputs is a dictionary (if provided)
- additional-inputs is string or array of strings (if provided)
- artifact-urns is array of strings (if provided)
- Artifact size limits (40MB per file)

#### Error Messages

Improved error messages for common issues:

- "Must provide either 'crew-ref' or 'crew' in request"
- "Cannot specify both 'crew-ref' and 'crew'; provide only one"
- "Invalid schema identifier. Expected 'urn:sd-core:schema.crewai.request.1'"
- "Failed to process additional inputs: {error details}"

---

### Examples

#### Example 1: Simple Research Request

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Quantum Computing Research",
  "crew-ref": "urn:ivcap:aspect:deep-research-crew",
  "inputs": {
    "research_topic": "Quantum Machine Learning",
    "keywords": "QSVM, quantum neural networks",
    "additional_information": "Focus on healthcare applications"
  }
}
```

#### Example 2: Research with Previous Context

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Synthesis Analysis",
  "crew-ref": "urn:ivcap:aspect:analysis-crew",
  "inputs": {
    "topic": "AI Safety Alignment",
    "focus_area": "scalable oversight mechanisms"
  },
  "additional-inputs": [
    "# Deep Research on AI Safety\n\nKey findings...",
    "# Expert Profiles\n\nDr. Sarah Chen leads research..."
  ]
}
```

#### Example 3: Document Processing with Artifacts

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Document Analysis",
  "crew-ref": "urn:ivcap:aspect:document-reader",
  "inputs": {},
  "artifact-urns": [
    "urn:ivcap:artifact:research-paper-1.pdf",
    "urn:ivcap:artifact:dataset-metadata.csv"
  ]
}
```

#### Example 4: Custom LLM Model

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Advanced Analysis",
  "crew-ref": "urn:ivcap:aspect:expert-analysis",
  "inputs": {
    "research_topic": "Climate Modeling",
    "llm_model": "claude-3-opus-20240229"
  }
}
```

---

### Troubleshooting

#### Common Issues

**Issue 1: "Invalid schema identifier" error**

- **Cause:** Missing or incorrect $schema field
- **Fix:** Ensure `"$schema": "urn:sd-core:schema.crewai.request.1"` is present

**Issue 2: "Must provide either 'crew-ref' or 'crew'" error**

- **Cause:** Neither crew-ref nor inline crew provided
- **Fix:** Add `"crew-ref": "urn:ivcap:aspect:..."` to request body

**Issue 3: Placeholders not replaced in crew execution**

- **Cause:** Input key names don't match crew's placeholder names
- **Fix:** Check crew definition's placeholders array and match exactly

**Issue 4: Previous outputs not searchable**

- **Cause:** Using `inputs.additional_information` instead of `additional-inputs`
- **Fix:** Move previous outputs to top-level `additional-inputs` field

**Issue 5: "Failed to parse request body" error**

- **Cause:** Request body not properly JSON-stringified
- **Fix:** Use `JSON.stringify(requestBody)` when setting parameter value

---

### References

#### Documentation

- [TESTING.md](TESTING.md) - Testing guide with examples
- [CLAUDE.md](docs_context/CLAUDE.md) - Architecture and implementation details
- [TESTING_GUIDE.md](TESTING_GUIDE.md) - Comprehensive testing scenarios

#### Examples

- [examples/simple_crew2_request.json](examples/simple_crew2_request.json) - Basic request format
- [examples/knowledge_request.json](examples/knowledge_request.json) - Request with knowledge sources
- [examples/document_reader_request.json](examples/document_reader_request.json) - Request with artifacts

#### Tests

- [tests/test_knowledge_integration.py](tests/test_knowledge_integration.py) - Knowledge sources tests
- [tests/test_knowledge_processor.py](tests/test_knowledge_processor.py) - Knowledge processor tests

#### Crew Definitions

- [crews/deep_search.json](crews/deep_search.json) - Example crew with all placeholders
- [crews/brainstorming.json](crews/brainstorming.json) - Example crew definition

---

## [0.1.0] - Legacy

### Original Implementation

The original service used a parameter-array format for simplicity but lacked structure for advanced features.

**Request Format:**

```json
{
  "service": "urn:ivcap:service:01555c28-32d0-5839-b92b-f3e52410d6dd",
  "parameters": [
    { "name": "crew", "value": "urn:ivcap:aspect:crew-definition" },
    { "name": "p1", "value": "keywords:AI, ML" },
    { "name": "p2", "value": "research_topic:Topic" },
    { "name": "p3", "value": "additional_information:Context" }
  ]
}
```

**Features:**

- Basic crew execution
- Simple placeholder replacement
- No knowledge sources
- No artifact support
- No structured validation

**Limitations:**

- Colon-prefix parsing was fragile
- No separation between inputs and knowledge context
- Limited extensibility
- No schema versioning

---

## Version History Summary

| Version | Date       | Status      | Key Changes |
|---------|------------|-------------|-------------|
| 0.2.0   | 2025-01-13 | Current     | Structured JSON request, knowledge sources, breaking changes |
| 0.1.0   | Legacy     | Deprecated  | Original parameter-array format |

---

## Support

For questions or issues with migration:

1. Review the Migration Guide above
2. Check examples/ directory for working request examples
3. Run tests in tests/ directory for validation
4. Contact the backend team for assistance

---

**Note:** This changelog follows [Keep a Changelog](https://keepachangelog.com/) and uses [Semantic Versioning](https://semver.org/). Breaking changes increment the minor version (0.1.x → 0.2.0) until we reach v1.0.0.
