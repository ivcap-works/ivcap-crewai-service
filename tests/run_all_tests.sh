#!/bin/bash
# Run all crew tests in parallel batches
# Usage: ./run_all_tests.sh [batch_size]
# Default batch size: 6

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
BATCH_SIZE=${1:-6}
SERVICE_URL="http://localhost:8077"
TIMEOUT=360
RESULTS_DIR="test_results_$(date +%Y%m%d_%H%M%S)"

# Check if service is running
echo -e "${BLUE}=== Checking if service is running ===${NC}"
if ! curl -s -f "$SERVICE_URL/health" > /dev/null 2>&1; then
    if ! curl -s -f "$SERVICE_URL/" > /dev/null 2>&1; then
        echo -e "${RED}Error: Service not running on $SERVICE_URL${NC}"
        echo -e "${YELLOW}Start the service with: poetry ivcap run${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✓ Service is running${NC}"
echo ""

# Get all test files
TEST_FILES=(
    tests/creativity_enhancement_test.json
    tests/funding_finder_test.json
    tests/brainstorming_copilot_test.json
    tests/expert_profiles_test.json
    tests/die_test.json
    tests/disease_mechanism_test.json
    tests/asa_test.json
    tests/expert_finder_test.json
    tests/topic_overview_test.json
    tests/scientific_review_writer_test.json
    tests/manuscript_template_test.json
    tests/market_research_test.json
    tests/grant_proposal_test.json
    tests/patent_search_test.json
    tests/risk_analysis_test.json
    tests/patent_landscape_test.json
    tests/competitive_analysis_test.json
    tests/software_discovery_aspect_test.json
    tests/software_discovery_data_analysis.json
)

TOTAL_TESTS=${#TEST_FILES[@]}

echo -e "${BLUE}=== Running $TOTAL_TESTS tests in batches of $BATCH_SIZE ===${NC}"
echo -e "${BLUE}Results will be saved to: $RESULTS_DIR${NC}"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Function to run a single test
run_test() {
    local test_file=$1
    local test_name=$(basename "$test_file" .json)
    local result_file="$RESULTS_DIR/${test_name}_result.json"
    local log_file="$RESULTS_DIR/${test_name}_log.txt"
    local start_time=$(date +%s)
    
    echo -e "${CYAN}[$(date +%H:%M:%S)] Starting: $test_name${NC}" | tee -a "$log_file"
    
    # Run the test and capture both stdout and stderr
    if curl -X POST \
        -H "Timeout: $TIMEOUT" \
        -H "content-type: application/json" \
        --data @"$test_file" \
        "$SERVICE_URL" \
        > "$result_file" 2>> "$log_file"; then
        
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        # Check if response is valid JSON
        if jq empty "$result_file" 2>/dev/null; then
            echo -e "${GREEN}✓ [$(date +%H:%M:%S)] Completed: $test_name (${duration}s)${NC}" | tee -a "$log_file"
            echo "$duration" > "$RESULTS_DIR/${test_name}_duration.txt"
            return 0
        else
            echo -e "${RED}✗ [$(date +%H:%M:%S)] Invalid JSON: $test_name (${duration}s)${NC}" | tee -a "$log_file"
            echo "ERROR: Invalid JSON response" >> "$log_file"
            return 1
        fi
    else
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo -e "${RED}✗ [$(date +%H:%M:%S)] Failed: $test_name (${duration}s)${NC}" | tee -a "$log_file"
        return 1
    fi
}

export -f run_test
export SERVICE_URL TIMEOUT RESULTS_DIR RED GREEN YELLOW BLUE CYAN NC

# Run tests in batches
batch_num=1
for ((i=0; i<$TOTAL_TESTS; i+=BATCH_SIZE)); do
    batch_end=$((i + BATCH_SIZE))
    if [ $batch_end -gt $TOTAL_TESTS ]; then
        batch_end=$TOTAL_TESTS
    fi
    
    echo -e "${YELLOW}=== Batch $batch_num: Tests $((i+1))-$batch_end ===${NC}"
    
    # Get batch of test files
    batch_files=("${TEST_FILES[@]:$i:$BATCH_SIZE}")
    
    # Run batch in parallel
    printf '%s\n' "${batch_files[@]}" | xargs -n 1 -P $BATCH_SIZE -I {} bash -c 'run_test "$@"' _ {}
    
    # Wait for batch to complete before starting next
    wait
    
    echo -e "${BLUE}Batch $batch_num complete${NC}"
    echo ""
    
    batch_num=$((batch_num + 1))
done

# Generate summary report
echo -e "${BLUE}=== Generating Summary Report ===${NC}"
SUMMARY_FILE="$RESULTS_DIR/SUMMARY.md"

cat > "$SUMMARY_FILE" << EOF
# Test Execution Summary

**Date**: $(date)
**Total Tests**: $TOTAL_TESTS
**Batch Size**: $BATCH_SIZE
**Service URL**: $SERVICE_URL

## Results

| Test Name | Status | Duration | Details |
|-----------|--------|----------|---------|
EOF

# Analyze results
SUCCESS_COUNT=0
FAIL_COUNT=0

for test_file in "${TEST_FILES[@]}"; do
    test_name=$(basename "$test_file" .json)
    result_file="$RESULTS_DIR/${test_name}_result.json"
    duration_file="$RESULTS_DIR/${test_name}_duration.txt"
    
    if [ -f "$result_file" ] && jq empty "$result_file" 2>/dev/null; then
        status="✅ Success"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        
        # Try to extract crew name and token usage
        crew_name=$(jq -r '.crew_name // "Unknown"' "$result_file" 2>/dev/null)
        tokens=$(jq -r '.token_usage.total_tokens // "N/A"' "$result_file" 2>/dev/null)
        
        if [ -f "$duration_file" ]; then
            duration=$(cat "$duration_file")
            details="$crew_name, ${tokens} tokens"
        else
            duration="N/A"
            details="$crew_name"
        fi
    else
        status="❌ Failed"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        duration="N/A"
        details="See ${test_name}_log.txt"
    fi
    
    echo "| $test_name | $status | ${duration}s | $details |" >> "$SUMMARY_FILE"
done

# Add summary statistics
cat >> "$SUMMARY_FILE" << EOF

## Summary Statistics

- **Successful**: $SUCCESS_COUNT / $TOTAL_TESTS
- **Failed**: $FAIL_COUNT / $TOTAL_TESTS
- **Success Rate**: $(awk "BEGIN {printf \"%.1f\", ($SUCCESS_COUNT/$TOTAL_TESTS)*100}")%

## Total Token Usage

EOF

# Calculate total tokens if possible
TOTAL_TOKENS=0
for test_file in "${TEST_FILES[@]}"; do
    test_name=$(basename "$test_file" .json)
    result_file="$RESULTS_DIR/${test_name}_result.json"
    
    if [ -f "$result_file" ]; then
        tokens=$(jq -r '.token_usage.total_tokens // 0' "$result_file" 2>/dev/null)
        TOTAL_TOKENS=$((TOTAL_TOKENS + tokens))
    fi
done

echo "**Total tokens across all tests**: $TOTAL_TOKENS" >> "$SUMMARY_FILE"

# Calculate total time
TOTAL_TIME=0
for test_file in "${TEST_FILES[@]}"; do
    test_name=$(basename "$test_file" .json)
    duration_file="$RESULTS_DIR/${test_name}_duration.txt"
    
    if [ -f "$duration_file" ]; then
        duration=$(cat "$duration_file")
        TOTAL_TIME=$((TOTAL_TIME + duration))
    fi
done

cat >> "$SUMMARY_FILE" << EOF

## Execution Time

- **Total wall time**: ${TOTAL_TIME}s ($(awk "BEGIN {printf \"%.1f\", $TOTAL_TIME/60}") minutes)
- **Average per test**: $(awk "BEGIN {printf \"%.1f\", $TOTAL_TIME/$SUCCESS_COUNT}")s

## Files

All results saved to: \`$RESULTS_DIR/\`

- Individual results: \`{test_name}_result.json\`
- Execution logs: \`{test_name}_log.txt\`
- Duration tracking: \`{test_name}_duration.txt\`
- This summary: \`SUMMARY.md\`

## Quick Analysis Commands

\`\`\`bash
# View summary
cat $RESULTS_DIR/SUMMARY.md

# Check all successful tests
grep -l "crew_name" $RESULTS_DIR/*_result.json

# View specific test result
cat $RESULTS_DIR/software_discovery_aspect_test_result.json | jq

# Extract all final answers
for f in $RESULTS_DIR/*_result.json; do
  echo "=== \$(basename \$f) ==="
  jq -r '.answer' "\$f" | head -20
  echo ""
done
\`\`\`
EOF

# Display summary
echo ""
echo -e "${GREEN}=== Test Execution Complete ===${NC}"
echo ""
cat "$SUMMARY_FILE"
echo ""
echo -e "${BLUE}Full results saved to: $RESULTS_DIR/${NC}"
echo -e "${BLUE}Summary report: $RESULTS_DIR/SUMMARY.md${NC}"
echo ""

# Exit with error if any tests failed
if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${YELLOW}⚠ Warning: $FAIL_COUNT test(s) failed${NC}"
    exit 1
else
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
fi

