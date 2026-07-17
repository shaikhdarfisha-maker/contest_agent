#!/bin/bash
# Wait until Streamlit is accepting connections, then start ngrok
until curl -s http://localhost:8501 > /dev/null 2>&1; do
  echo "Waiting for Streamlit on port 8501..."
  sleep 3
done
echo "Streamlit is up — starting ngrok tunnel"
exec /opt/homebrew/bin/ngrok http \
  --url=shale-unfailing-backyard.ngrok-free.dev \
  --log=stdout \
  8501
