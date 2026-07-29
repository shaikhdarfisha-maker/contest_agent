#!/bin/bash
set -e

# Decode Scaler browser session from base64 secret
if [ -n "$STORAGE_STATE_B64" ]; then
    echo "$STORAGE_STATE_B64" | base64 -d > /app/data/storage_state.json
    echo "[entrypoint] storage_state.json written"
fi

# Decode Google service account credentials from base64 secret
# Accept both GOOGLE_CREDS_B64 (canonical) and SERVICE_ACCOUNT_B64 (legacy alias)
_GCREDS="${GOOGLE_CREDS_B64:-$SERVICE_ACCOUNT_B64}"
if [ -n "$_GCREDS" ]; then
    echo "$_GCREDS" | base64 -d > /app/data/service_account.json
    echo "[entrypoint] service_account.json written"
fi

exec streamlit run streamlit_app.py \
    --server.port=7860 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
