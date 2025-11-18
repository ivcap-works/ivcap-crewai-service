# Brainstorming with Artifacts Test

## Purpose

This test demonstrates the **smart artifact handling** feature where artifacts (PDFs) are automatically converted to knowledge sources for crews that don't explicitly use DirectoryReadTool.

## How It Works

The Brainstorming Copilot crew has no DirectoryReadTool or "research"/"search" keywords in agent roles, so the service automatically:

1. Downloads the PDF artifacts
2. Converts them to `PDFKnowledgeSource` instances
3. Passes them to the crew via `knowledge_sources` parameter
4. All agents get automatic RAG access to the PDF content

## Test Command

```bash
# Start the service
poetry ivcap run

# In another terminal, run the test
curl -X POST http://localhost:8077/ \
  -H "Authorization: Bearer $IVCAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d @examples/brainstorming_with_artifacts_request.json
```

## Expected Behavior

### Logs should show:
```
INFO: Downloading 2 artifacts...
INFO: Downloaded 2/2 artifacts
INFO: Loaded crew definition: Brainstorming Copilot
INFO: 📚 Crew has no DirectoryReadTool or research/search agents - using knowledge sources
INFO: ✓ PDF knowledge source: faw1.pdf
INFO: ✓ PDF knowledge source: faw2.pdf
INFO: ✓ Created 2 artifact knowledge sources
INFO:   All agents will have automatic RAG access to artifacts
INFO: 📚 Total knowledge sources for crew: 2
```

### The crew will:
1. Analyze the innovation mode (BREADTH for brainstorming)
2. Research context - **automatically queries PDF content via RAG**
3. Generate 15-20 solution ideas based on problems found in the PDFs
4. Validate ideas
5. Present formatted results

## Key Difference from Document Reader Crew

**Document Reader Crew** (has DirectoryReadTool):
- Uses tool injection approach
- Agents explicitly call PDFSearchTool/DirectoryReadTool
- Manual control over which files to read

**Brainstorming Copilot Crew** (no DirectoryReadTool):
- Uses knowledge source approach
- Agents automatically have RAG access
- Transparent semantic search across all PDFs
- No tool definitions needed in crew JSON

## Artifacts Used

- `urn:ivcap:artifact:8e485dca-f5cf-4e81-ab4a-b916066ec083` (faw1.pdf)
- `urn:ivcap:artifact:2569e489-33d5-47df-ab4a-9745d776e40e` (faw2.pdf)

These are healthcare research PDFs that should contain problems/challenges for the crew to address.

## Success Criteria

✅ Service detects crew has no DirectoryReadTool
✅ PDFs converted to knowledge sources
✅ Crew generates ideas based on problems found in documents
✅ Ideas reference specific content from the PDFs
✅ No tool-related errors

