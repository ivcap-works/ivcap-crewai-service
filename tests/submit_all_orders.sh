#!/bin/bash
# Submit all crew tests as IVCAP orders in batches
# Usage: ./submit_all_orders.sh [batch_size]
# Default batch size: 6
#
# This creates IVCAP jobs (not immediate execution)

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
DELAY_BETWEEN_BATCHES=${2:-5}  # Seconds to wait between batches

# Check prerequisites
if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is not installed${NC}"
    exit 1
fi

if ! command -v ivcap &> /dev/null; then
    echo -e "${RED}Error: ivcap CLI is not installed${NC}"
    exit 1
fi

echo -e "${BLUE}=== IVCAP Batch Job Submission ===${NC}"
echo ""

# Get credentials and service info
echo -e "${BLUE}Getting IVCAP credentials and service info...${NC}"
TOKEN=$(ivcap context get access-token --refresh-token 2>&1)
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to get authentication token${NC}"
    exit 1
fi

IVCAP_URL=$(ivcap context get url 2>&1)
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to get IVCAP URL${NC}"
    exit 1
fi

# Change to parent directory if in tests/
if [[ $(basename $(pwd)) == "tests" ]]; then
    cd ..
fi

SERVICE_ID=$(poetry ivcap --silent get-service-id 2>&1)
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Failed to get service ID${NC}"
    exit 1
fi

echo -e "${GREEN}✓ IVCAP URL: $IVCAP_URL${NC}"
echo -e "${GREEN}✓ Service ID: $SERVICE_ID${NC}"
echo ""

# Test files to submit
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
RESULTS_FILE="submitted_jobs_$(date +%Y%m%d_%H%M%S).txt"

echo -e "${BLUE}Submitting $TOTAL_TESTS jobs in batches of $BATCH_SIZE${NC}"
echo -e "${BLUE}Job IDs will be saved to: $RESULTS_FILE${NC}"
echo ""

# Initialize results file
echo "# IVCAP Job Submissions - $(date)" > "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"
echo "Service: $SERVICE_ID" >> "$RESULTS_FILE"
echo "Total Jobs: $TOTAL_TESTS" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"
echo "## Job IDs" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

# Function to submit a single job
submit_job() {
    local test_file=$1
    local test_name=$(basename "$test_file" .json)
    
    echo -e "${CYAN}[$(date +%H:%M:%S)] Submitting: $test_name${NC}"
    
    # Read and prepare request body
    if ! REQUEST_BODY=$(cat "$test_file" | jq -c . 2>&1); then
        echo -e "${RED}✗ Invalid JSON in $test_file${NC}"
        echo "$test_name: ERROR - Invalid JSON" >> "$RESULTS_FILE"
        return 1
    fi
    
    # Create order payload
    ORDER_PAYLOAD=$(jq -n \
        --arg service "$SERVICE_ID" \
        --arg body "$REQUEST_BODY" \
        '{
            service: $service,
            parameters: [
                {
                    name: "body",
                    value: $body
                }
            ]
        }')
    
    # Submit to IVCAP
    RESPONSE=$(curl -s -X POST \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -H "Timeout: 360" \
        --data "$ORDER_PAYLOAD" \
        "$IVCAP_URL/1/services2/$SERVICE_ID/jobs")
    
    # Extract job ID
    JOB_ID=$(echo "$RESPONSE" | jq -r '.id // empty' 2>/dev/null)
    
    if [ -n "$JOB_ID" ]; then
        echo -e "${GREEN}✓ [$(date +%H:%M:%S)] Job created: $test_name${NC}"
        echo "$test_name: $JOB_ID" >> "$RESULTS_FILE"
        echo "$JOB_ID"
        return 0
    else
        echo -e "${RED}✗ [$(date +%H:%M:%S)] Failed: $test_name${NC}"
        echo "$test_name: ERROR - $(echo $RESPONSE | jq -r '.message // "Unknown error"' 2>/dev/null)" >> "$RESULTS_FILE"
        return 1
    fi
}

export -f submit_job
export TOKEN IVCAP_URL SERVICE_ID RESULTS_FILE RED GREEN CYAN NC

# Submit jobs in batches
batch_num=1
SUCCESS_COUNT=0
FAIL_COUNT=0
ALL_JOB_IDS=()

for ((i=0; i<$TOTAL_TESTS; i+=BATCH_SIZE)); do
    batch_end=$((i + BATCH_SIZE))
    if [ $batch_end -gt $TOTAL_TESTS ]; then
        batch_end=$TOTAL_TESTS
    fi
    
    echo -e "${YELLOW}=== Batch $batch_num: Submitting jobs $((i+1))-$batch_end ===${NC}"
    
    # Get batch of test files
    batch_files=("${TEST_FILES[@]:$i:$BATCH_SIZE}")
    
    # Submit batch in parallel and collect job IDs
    BATCH_JOB_IDS=()
    for test_file in "${batch_files[@]}"; do
        JOB_ID=$(submit_job "$test_file")
        if [ -n "$JOB_ID" ] && [[ "$JOB_ID" == urn:ivcap:job:* ]]; then
            BATCH_JOB_IDS+=("$JOB_ID")
            ALL_JOB_IDS+=("$JOB_ID")
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        else
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    done &
    wait
    
    echo -e "${BLUE}Batch $batch_num submitted: ${#BATCH_JOB_IDS[@]} jobs${NC}"
    
    # Delay between batches to avoid overwhelming IVCAP
    if [ $batch_end -lt $TOTAL_TESTS ]; then
        echo -e "${YELLOW}Waiting ${DELAY_BETWEEN_BATCHES}s before next batch...${NC}"
        sleep $DELAY_BETWEEN_BATCHES
    fi
    
    echo ""
    batch_num=$((batch_num + 1))
done

# Add monitoring commands to results file
cat >> "$RESULTS_FILE" << EOF

## Monitoring Commands

### Check all job statuses
\`\`\`bash
TOKEN=\$(ivcap context get access-token --refresh-token)
IVCAP_URL=\$(ivcap context get url)
SERVICE_ID=$SERVICE_ID

EOF

for JOB_ID in "${ALL_JOB_IDS[@]}"; do
    cat >> "$RESULTS_FILE" << EOF
# $(grep "$JOB_ID" "$RESULTS_FILE" | head -1 | cut -d: -f1)
curl -H "Authorization: Bearer \$TOKEN" "\$IVCAP_URL/1/services2/\$SERVICE_ID/jobs/$JOB_ID" | jq -r '.status'

EOF
done

cat >> "$RESULTS_FILE" << EOF
\`\`\`

### Get results for completed jobs
\`\`\`bash
TOKEN=\$(ivcap context get access-token --refresh-token)
IVCAP_URL=\$(ivcap context get url)
SERVICE_ID=$SERVICE_ID

EOF

for JOB_ID in "${ALL_JOB_IDS[@]}"; do
    cat >> "$RESULTS_FILE" << EOF
# $(grep "$JOB_ID" "$RESULTS_FILE" | head -1 | cut -d: -f1)
curl -H "Authorization: Bearer \$TOKEN" "\$IVCAP_URL/1/services2/\$SERVICE_ID/jobs/$JOB_ID?with-result-content=true" | jq

EOF
done

echo "\`\`\`" >> "$RESULTS_FILE"

# Display summary
echo -e "${GREEN}=== Batch Submission Complete ===${NC}"
echo ""
echo -e "${GREEN}Successfully submitted: $SUCCESS_COUNT jobs${NC}"
if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}Failed: $FAIL_COUNT jobs${NC}"
fi
echo ""
echo -e "${BLUE}Job IDs saved to: $RESULTS_FILE${NC}"
echo ""
echo -e "${YELLOW}=== Quick Commands ===${NC}"
echo ""
echo "Check status of all jobs:"
echo -e "${CYAN}  grep 'urn:ivcap:job:' $RESULTS_FILE${NC}"
echo ""
echo "Monitor first job:"
if [ ${#ALL_JOB_IDS[@]} -gt 0 ]; then
    FIRST_JOB=${ALL_JOB_IDS[0]}
    echo -e "${CYAN}  curl -H \"Authorization: Bearer \$(ivcap context get access-token --refresh-token)\" \\${NC}"
    echo -e "${CYAN}    \"\$(ivcap context get url)/1/services2/$SERVICE_ID/jobs/$FIRST_JOB\" | jq .status${NC}"
fi
echo ""
echo "See full monitoring commands in:"
echo -e "${CYAN}  cat $RESULTS_FILE${NC}"
echo ""

# Exit with error if any submissions failed
if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
else
    exit 0
fi

