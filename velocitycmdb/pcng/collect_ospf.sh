#!/bin/bash
#
# OSPF Analytics Collection Script
# Collects OSPF neighbor data from Arista and Juniper devices
#

set -e

# Configuration
SESSIONS_FILE="${SESSIONS_FILE:-$HOME/.velocitycmdb/data/sessions.yaml}"
OUTPUT_DIR="${OUTPUT_DIR:-ospf_analytics}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
MAX_WORKERS="${MAX_WORKERS:-12}"
TIMEOUT="${TIMEOUT:-20}"
SHELL_TIMEOUT="${SHELL_TIMEOUT:-10}"

# Credentials - set these or export before running
export CRED_1_USER="${CRED_1_USER:-$USER}"
export CRED_2_USER="${CRED_2_USER:-$USER}"
export CRED_3_USER="${CRED_3_USER:-$USER}"
export PYSSH_KEY="$SSH_KEY"

echo "=============================================="
echo "OSPF Analytics Collection"
echo "=============================================="
echo "Sessions file: $SESSIONS_FILE"
echo "Output dir:    $OUTPUT_DIR"
echo "SSH Key:       $SSH_KEY"
echo "Max workers:   $MAX_WORKERS"
echo "User:          $CRED_1_USER"
echo "=============================================="
echo ""

# Check prerequisites
if [ ! -f "$SESSIONS_FILE" ]; then
    echo "ERROR: Sessions file not found: $SESSIONS_FILE"
    exit 1
fi

if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found: $SSH_KEY"
    exit 1
fi

# Collect from Arista devices
echo ">>> Collecting OSPF data from Arista devices..."
python batch_spn.py "$SESSIONS_FILE" \
    --vendor arista \
    --use-keys --ssh-key "$SSH_KEY" \
    -c "term len 0,show ip ospf nei detail,," \
    -o "$OUTPUT_DIR" \
    --timeout "$TIMEOUT" \
    --shell-timeout "$SHELL_TIMEOUT" \
    --prompt "#" \
    --prompt-count 4 \
    --max-workers "$MAX_WORKERS"

echo ""

# Collect from Juniper devices
echo ">>> Collecting OSPF data from Juniper devices..."
python batch_spn.py "$SESSIONS_FILE" \
    --vendor juniper \
    --use-keys --ssh-key "$SSH_KEY" \
    -c "show ospf neighbor extensive | no-more" \
    -o "$OUTPUT_DIR" \
    --timeout "$TIMEOUT" \
    --shell-timeout "$SHELL_TIMEOUT" \
    --prompt ">" \
    --prompt-count 2 \
    --max-workers "$MAX_WORKERS"

echo ""
echo "=============================================="
echo "Collection complete!"
echo "Output files in: capture/$OUTPUT_DIR/"
echo "=============================================="