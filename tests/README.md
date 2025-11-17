# IVCAP CrewAI Service Tests

This directory contains test files and utilities for the IVCAP CrewAI Service.

## Test Categories

### Integration Tests

Python-based integration tests for service features:

- **test_knowledge_integration.py** - Tests for knowledge sources (`additional-inputs`) feature
- **test_knowledge_processor.py** - Unit tests for knowledge processor module
- **test_knowledge_simple.py** - Simple smoke tests for knowledge sources
- **runembedding_test.py** - Tests for embedding functionality

### Crew Test Requests

run all as :
`parallel --gnu -j 5 'make test-local-with-auth TEST_REQUEST={}' ::: tests/*json`

JSON test request files for all deployed crews (v0.2.0 format with entity URN references):

#### Research & Discovery

- **software_discovery_aspect_test.json** - ML training infrastructure tool discovery
- **software_discovery_data_analysis.json** - Bioinformatics tools discovery
- **expert_finder_test.json** - Climate modeling expert identification
- **expert_profiles_test.json** - Quantum computing researcher profiling
- **topic_overview_test.json** - CRISPR gene editing literature review

#### Innovation & Creativity

- **creativity_enhancement_test.json** - Sustainable packaging material ideation
- **brainstorming_copilot_test.json** - Healthcare AI diagnostic system innovation
- **die_test.json** - Disruptive hypothesis for dark matter anomalies

#### Scientific & Medical

- **disease_mechanism_test.json** - Alzheimer's neuroinflammation investigation
- **asa_test.json** - Synthetic biology research workflow design
- **scientific_review_writer_test.json** - Adult neuroplasticity review manuscript
- **manuscript_template_test.json** - Nature Medicine article template

#### Business & Strategy

- **market_research_test.json** - Quantum sensor commercialization analysis
- **competitive_analysis_test.json** - Enterprise LLM platform competitive intel
- **funding_finder_test.json** - Global funding search for AI safety research
- **grant_proposal_test.json** - NIH R01 Alzheimer's grant writing

#### Intellectual Property

- **patent_search_test.json** - mRNA delivery system patent landscape
- **patent_landscape_test.json** - CAR-T therapy patent + regulatory analysis
- **risk_analysis_test.json** - Phase II clinical trial risk assessment

### Test Utilities

- **create_order.sh** - Create single IVCAP order from test file (creates job, doesn't execute immediately)
- **submit_all_orders.sh** - Submit all tests as IVCAP orders in parallel batches (creates jobs)
- **run_all_tests.sh** - Execute all tests directly on local service (immediate execution, no jobs)

### Test Crews

The `test_crews/` directory contains crew definitions used for testing:

- **context_chain.json** - Test crew for task context chaining

## Running Tests

### Python Integration Tests

```bash
# Run knowledge integration tests
python tests/test_knowledge_integration.py

# Run knowledge processor tests
python tests/test_knowledge_processor.py

# Run simple knowledge tests
python tests/test_knowledge_simple.py
```

### Crew Request Tests

See individual README files for specific crew testing instructions:

- **[Software Discovery Crew](README_SOFTWARE_DISCOVERY.md)** - Complete guide for testing the Software Discovery crew with multiple methods

### Quick Test Commands

```bash
# Run all tests in parallel (6 at a time by default)
tests/run_all_tests.sh

# Run all tests with custom batch size
tests/run_all_tests.sh 3  # Run 3 at a time
tests/run_all_tests.sh 10 # Run 10 at a time

# Test individual crew locally (requires service running on port 8077)
make test-local TEST_REQUEST=tests/software_discovery_aspect_test.json
make test-local TEST_REQUEST=tests/grant_proposal_test.json
make test-local TEST_REQUEST=tests/disease_mechanism_test.json

# Create IVCAP order using helper script (requires service deployed to IVCAP)
tests/create_order.sh tests/software_discovery_aspect_test.json
tests/create_order.sh tests/creativity_enhancement_test.json
tests/create_order.sh tests/patent_search_test.json

# Test with authentication
make test-local-with-auth TEST_REQUEST=tests/market_research_test.json

# Create IVCAP order via Makefile
make test-job-ivcap TEST_REQUEST=tests/competitive_analysis_test.json
```

## Test File Format

All crew test request files follow the v0.2.0 format:

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  "name": "Test Job Name",
  "crew-ref": "urn:sd:crewai:crew.crew_name",
  "inputs": {
    "placeholder1": "value1",
    "placeholder2": "value2"
  }
}
```

### Key Points

- Use `crew-ref` with **entity URN** (e.g., `urn:sd:crewai:crew.software_discovery`)
- Do NOT use artifact URN in `crew-ref`
- Include `$schema` field for validation
- Provide all required placeholders in `inputs` dictionary
- Most crews use three standard placeholders: `research_topic`, `keywords`, `additional_information`

### Available Crews

All test files reference crews deployed in IVCAP with these entity URNs:

| Crew Name                | Entity URN                                             | Primary Use Case                         |
| ------------------------ | ------------------------------------------------------ | ---------------------------------------- |
| Software Discovery       | `urn:sd:crewai:crew.software_discovery`              | Find and evaluate software tools         |
| Expert Finder            | `urn:sd:crewai:crew.expert_finder`                   | Identify and rank subject matter experts |
| Expert Profiles          | `urn:sd:crewai:crew.expert_profiles`                 | Create detailed expert profiles          |
| Topic Overview           | `urn:sd:crewai:crew.topic_overview`                  | Systematic literature review             |
| Deep Research            | `urn:sd:crewai:crew.deepresearch`                    | Comprehensive web research               |
| Creativity Enhancement   | `urn:sd:crewai:crew.creativity_enhancement`          | Structured creative ideation             |
| Brainstorming Copilot    | `urn:sd:crewai:crew.brainstorming_copilot`           | Adaptive innovation (breadth/depth)      |
| DIE                      | `urn:sd:crewai:crew.die`                             | Disruptive hypothesis from anomalies     |
| Disease Mechanism        | `urn:sd:crewai:crew.disease_mechanism_investigation` | Disease pathway analysis                 |
| ASA                      | `urn:sd:crewai:crew.asa`                             | Research workflow design                 |
| Scientific Review Writer | `urn:sd:crewai:crew.scientific_review_writer`        | Review manuscript writing                |
| Manuscript Template      | `urn:sd:crewai:crew.manuscript_template_builder`     | Journal template extraction              |
| Market Research          | `urn:sd:crewai:crew.market_research`                 | Market analysis and GTM strategy         |
| Competitive Analysis     | `urn:sd:crewai:crew.competitive_analysis`            | Competitive intelligence                 |
| Funding Finder           | `urn:sd:crewai:crew.funding_finder`                  | Global funding opportunities             |
| Grant Proposal           | `urn:sd:crewai:crew.grant_proposal`                  | Grant proposal writing                   |
| Patent Search            | `urn:sd:crewai:crew.patent_search`                   | Patent landscape analysis                |
| Patent Landscape         | `urn:sd:crewai:crew.patent_landscape`                | Patent + regulatory review               |
| Risk Analysis            | `urn:sd:crewai:crew.risk_analysis`                   | Risk assessment and mitigation           |

## Creating New Tests

### For New Crews

1. Create a JSON test request file: `tests/{crew_name}_test.json`
2. Use the v0.2.0 format with proper entity URN
3. Document expected behavior and results
4. Consider creating a dedicated README if the crew has multiple test scenarios

### For Integration Tests

1. Create a Python test file: `tests/test_{feature_name}.py`
2. Use pytest framework
3. Include docstrings explaining what's being tested
4. Add to this README's integration tests section

## Helper Scripts

### create_order.sh

Simplifies IVCAP order creation from test JSON files.

**Usage**:

```bash
tests/create_order.sh tests/software_discovery_aspect_test.json
```

**Features**:

- Automatic token and URL retrieval
- JSON validation
- Proper order payload formatting
- Returns job ID and monitoring commands

**Requirements**:

- ivcap CLI installed and configured
- jq installed
- Script is executable (`chmod +x tests/create_order.sh`)

### run_all_tests.sh ⚡ Local Execution

**Purpose**: Execute all tests directly on local service (immediate results, no IVCAP jobs)

**Usage**:

```bash
# Default batch size (6 tests at a time)
tests/run_all_tests.sh

# Custom batch size
tests/run_all_tests.sh 3   # Safer for resource-constrained systems
tests/run_all_tests.sh 10  # Faster on powerful machines
```

**What it does**: Posts test requests directly to localhost:8077 and waits for results

**Features**:

- ⚡ Immediate execution (no job queue)
- Parallel execution in configurable batches
- Automatic results collection
- Duration tracking per test
- Token usage aggregation
- Summary report generation

**Output**: `test_results_YYYYMMDD_HHMMSS/` with all results and SUMMARY.md

**Requirements**: Service running on localhost:8077

---

### submit_all_orders.sh 📋 IVCAP Jobs

**Purpose**: Submit all tests as IVCAP orders (creates jobs that execute on IVCAP, not immediately)

**Usage**:

```bash
# Default batch size (6 orders at a time)
tests/submit_all_orders.sh

# Custom batch size and delay
tests/submit_all_orders.sh 3 10  # 3 at a time, 10s delay between batches
```

**What it does**: Creates IVCAP job orders that will execute on IVCAP infrastructure

**Features**:

- 📋 Creates job orders (not immediate execution)
- Parallel submission in configurable batches
- Saves all job IDs for monitoring
- Generates monitoring commands
- Delay between batches to avoid overwhelming API

**Output**: `submitted_jobs_YYYYMMDD_HHMMSS.txt` with job IDs and monitoring commands

**Requirements**:

- ivcap CLI configured with authentication
- Service deployed to IVCAP
- jq installed

**Example Output**:

```
=== IVCAP Batch Job Submission ===

✓ IVCAP URL: https://mindweaver.develop.ivcap.io
✓ Service ID: urn:ivcap:service:01555c28...

=== Batch 1: Submitting jobs 1-6 ===
✓ Job created: creativity_enhancement_test
✓ Job created: funding_finder_test
...

Successfully submitted: 19 jobs
Job IDs saved to: submitted_jobs_20250114_103045.txt
```

---

**Key Difference**:

- `run_all_tests.sh` → Direct service execution (localhost, immediate results)
- `submit_all_orders.sh` → IVCAP job creation (queued, async execution)

## Test Data

Test crews and configurations are stored in:

- `test_crews/` - Crew definitions for testing
- Individual JSON files - Request payloads for specific test scenarios

## Troubleshooting

### "cannot find crew definition"

The crew must be uploaded to IVCAP as an aspect. Verify with:

```bash
ivcap aspect query -s "urn:sd:schema:icrew-crew.1" --entity "urn:sd:crewai:crew.{crew_name}" -o json
```

### "Invalid schema identifier"

Ensure your test file includes:

```json
{
  "$schema": "urn:sd-core:schema.crewai.request.1",
  ...
}
```

### Service not responding

Check if the service is running:

```bash
# Should show service listening on port 8077
curl http://localhost:8077/health
```

Start service if needed:

```bash
poetry ivcap run
```

## Additional Documentation

- [Software Discovery Testing Guide](README_SOFTWARE_DISCOVERY.md) - Comprehensive testing guide for Software Discovery crew
- [Service README](../README.md) - Main service documentation
- [CHANGELOG](../CHANGELOG.md) - Version history and migration guide
- [Testing Guide](../TESTING.md) - General testing guide for the service
- [Architecture Guide](../docs_context/CLAUDE.md) - Service architecture and implementation details

## Environment Setup

Ensure your `.env` file contains:

```bash
# Required
IVCAP_BASE_URL=http://ivcap.local
LITELLM_PROXY_URL=http://localhost:8000

# For web search tools
SERPER_API_KEY=your_api_key

# Model configuration
LITELLM_DEFAULT_MODEL=gpt-4o
```

## Contributing

When adding new tests:

1. Follow the v0.2.0 request format
2. Document expected behavior
3. Include validation criteria
4. Add to this README
5. Consider creating a dedicated README for complex test scenarios
