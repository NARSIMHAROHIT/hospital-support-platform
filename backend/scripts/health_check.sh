#!/bin/bash

URL="http://127.0.0.1:8000/health"

echo "Checking Hospital Support API..."

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  --max-time 5 "$URL")

if [ "$STATUS" = "200" ]; then
    echo "SUCCESS: API is healthy"
    exit 0
else
    echo "ERROR: API returned HTTP $STATUS"
    exit 1
fi
