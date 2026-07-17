#!/bin/bash
# Starts Streamlit + ngrok tunnel in one command.
# Share: https://shale-unfailing-backyard.ngrok-free.dev/

set -e

cd "$(dirname "$0")"

# Load .env
export $(grep -v '^#' .env | xargs) 2>/dev/null || true

echo "Starting Streamlit..."
streamlit run streamlit_app.py --server.port 8501 --server.headless true &
STREAMLIT_PID=$!

# Give Streamlit a moment to bind the port
sleep 3

echo "Starting ngrok tunnel..."
ngrok http --domain=shale-unfailing-backyard.ngrok-free.dev 8501 &
NGROK_PID=$!

echo ""
echo "=========================================="
echo "  App live at:"
echo "  https://shale-unfailing-backyard.ngrok-free.dev/"
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop both services."

# Wait and clean up on exit
trap "kill $STREAMLIT_PID $NGROK_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait
