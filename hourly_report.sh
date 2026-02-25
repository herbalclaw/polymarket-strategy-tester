#!/bin/bash
# Simple hourly report that runs via heartbeat — no cron job needed
# This script is called by heartbeat check to generate reports

cd /root/.openclaw/workspace/polymarket-strategy-tester

# Check if it's been an hour since last report
LAST_REPORT_FILE=".last_hourly_report"
CURRENT_TIME=$(date +%s)

if [ -f "$LAST_REPORT_FILE" ]; then
    LAST_REPORT=$(cat "$LAST_REPORT_FILE")
    TIME_DIFF=$((CURRENT_TIME - LAST_REPORT))
    # Only report if 1 hour (3600 seconds) has passed
    if [ $TIME_DIFF -lt 3600 ]; then
        exit 0
    fi
fi

# Generate and send report
python3 generate_hourly_report.py > /tmp/hourly_report.txt 2>&1

# Send via OpenClaw message tool (if available)
if command -v openclaw &> /dev/null; then
    openclaw message send --target "540600073" --file /tmp/hourly_report.txt
fi

# Update last report time
echo $CURRENT_TIME > "$LAST_REPORT_FILE"
