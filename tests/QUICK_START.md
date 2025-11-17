# Quick Start - Running All Crew Tests

## Two Approaches - Choose Your Testing Method

| Feature | run_all_tests.sh | submit_all_orders.sh |
|---------|------------------|----------------------|
| **Execution** | ⚡ Immediate (localhost) | 📋 Queued (IVCAP jobs) |
| **Results** | Returns immediately | Async, check later |
| **Use case** | Local development | Production testing |
| **Requires** | Service on localhost:8077 | Service deployed to IVCAP |
| **Output** | Full results in directory | Job IDs for monitoring |
| **Speed** | Fast feedback | Depends on IVCAP queue |

## Two Approaches

### Option 1: Local Execution (Immediate Results) ⚡

**Use when**: Testing locally, want immediate feedback, debugging

```bash
# Start service in Terminal 1
cd /Users/ran12c/development/ivcapworks/ivcap-crewai-service
poetry ivcap run

# Run all tests in Terminal 2
tests/run_all_tests.sh

# Results saved to: test_results_YYYYMMDD_HHMMSS/
```

**What happens**: Tests execute directly on localhost:8077, results returned immediately

---

### Option 2: IVCAP Job Submission (Async Execution) 📋

**Use when**: Testing on deployed service, want to queue jobs, production testing

```bash
# No local service needed - submits to IVCAP
tests/submit_all_orders.sh

# Job IDs saved to: submitted_jobs_YYYYMMDD_HHMMSS.txt
```

**What happens**: Creates IVCAP job orders that execute asynchronously on IVCAP infrastructure

---

## Prerequisites

### For Local Execution (run_all_tests.sh)

1. **Service running locally**:
```bash
cd /Users/ran12c/development/ivcapworks/ivcap-crewai-service
poetry ivcap run
```

2. **Environment configured** (`.env` file):
```bash
IVCAP_BASE_URL=http://ivcap.local
SERPER_API_KEY=your_serper_key
LITELLM_PROXY_URL=http://localhost:8000
```

### For IVCAP Job Submission (submit_all_orders.sh)

1. **ivcap CLI configured**:
```bash
ivcap context get url  # Should return IVCAP URL
ivcap context get access-token --refresh-token  # Should return token
```

2. **Service deployed to IVCAP**:
```bash
poetry ivcap docker-publish
poetry ivcap service-register
```

## What Happens

1. **Service check** - Verifies service is running on localhost:8077
2. **Batch 1** (6 tests run in parallel):
   - creativity_enhancement_test
   - funding_finder_test
   - brainstorming_copilot_test
   - expert_profiles_test
   - die_test
   - disease_mechanism_test

3. **Batch 2** (6 tests run in parallel):
   - asa_test
   - expert_finder_test
   - topic_overview_test
   - scientific_review_writer_test
   - manuscript_template_test
   - market_research_test

4. **Batch 3** (6 tests run in parallel):
   - grant_proposal_test
   - patent_search_test
   - risk_analysis_test
   - patent_landscape_test
   - competitive_analysis_test
   - software_discovery_aspect_test

5. **Batch 4** (1 test):
   - software_discovery_data_analysis_test

6. **Summary generation** - Creates report with:
   - Success/failure counts
   - Total token usage
   - Execution times
   - Individual test details

## Expected Output

```
=== Checking if service is running ===
✓ Service is running

=== Running 19 tests in batches of 6 ===
Results will be saved to: test_results_20250114_103045

=== Batch 1: Tests 1-6 ===
[10:30:45] Starting: creativity_enhancement_test
[10:30:45] Starting: funding_finder_test
[10:30:45] Starting: brainstorming_copilot_test
[10:30:45] Starting: expert_profiles_test
[10:30:45] Starting: die_test
[10:30:45] Starting: disease_mechanism_test
✓ [10:32:15] Completed: creativity_enhancement_test (90s)
✓ [10:32:30] Completed: die_test (105s)
✓ [10:33:00] Completed: brainstorming_copilot_test (135s)
✓ [10:33:45] Completed: funding_finder_test (180s)
✓ [10:34:00] Completed: expert_profiles_test (195s)
✓ [10:34:15] Completed: disease_mechanism_test (210s)
Batch 1 complete

=== Batch 2: Tests 7-12 ===
...

=== Test Execution Complete ===

# Test Execution Summary

**Date**: Mon Jan 14 10:45:23 PST 2025
**Total Tests**: 19
**Batch Size**: 6

Summary Statistics:
- Successful: 19 / 19
- Failed: 0 / 19
- Success Rate: 100.0%

Total Token Usage:
**Total tokens across all tests**: 245,678

Execution Time:
- Total wall time: 2115s (35.2 minutes)
- Average per test: 111.3s

🎉 All tests passed!
```

## View Results

```bash
# View summary report
cat test_results_*/SUMMARY.md

# View specific test result
cat test_results_*/software_discovery_aspect_test_result.json | jq

# Extract final answer from a test
jq -r '.answer' test_results_*/grant_proposal_test_result.json | head -50

# Check token usage for all tests
jq -r '.crew_name + ": " + (.token_usage.total_tokens | tostring)' test_results_*/*_result.json

# List all successful tests
ls test_results_*/*_result.json | wc -l
```

## Troubleshooting

### Service not running
```bash
# In Terminal 1
cd /Users/ran12c/development/ivcapworks/ivcap-crewai-service
poetry ivcap run
```

### Tests timing out
```bash
# Reduce batch size to avoid overwhelming the service
tests/run_all_tests.sh 3
```

### Some tests failing
```bash
# Check logs for specific test
cat test_results_*/failed_test_name_log.txt

# Check error in result
jq . test_results_*/failed_test_name_result.json
```

### Rate limiting or resource issues
```bash
# Run with smaller batch size
tests/run_all_tests.sh 2

# Or run tests sequentially
tests/run_all_tests.sh 1
```

## Estimated Timing

**Per test**: ~60-300 seconds (varies by crew complexity)

**Total time by batch size**:
- Batch of 1 (sequential): ~35-95 minutes
- Batch of 3: ~15-40 minutes  
- Batch of 6 (default): ~8-25 minutes
- Batch of 10: ~6-18 minutes

*Times vary based on LLM speed, web search latency, and crew complexity*

## Next Steps

After successful test run:

1. Review `SUMMARY.md` for overall statistics
2. Spot-check individual results for quality
3. Compare token usage across crews
4. Identify any failed tests for debugging
5. Deploy to IVCAP if all tests pass

