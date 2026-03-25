#!/bin/bash

echo "======================================"
echo "  Educational WhatsApp Chatbot        "
echo "======================================"

# Kill any process already using port 8000 to avoid [Errno 48] (macOS compatible)
echo "-> Clearing port 8000 if busy..."
# Try macOS lsof first
PIDS=$(lsof -t -i:8000 2>/dev/null)
if [ -n "$PIDS" ]; then
  echo "   Found stuck process(es): $PIDS — killing them..."
  kill -9 $PIDS 2>/dev/null
else
  # Fallback for Linux/EC2 without lsof
  fuser -k 8000/tcp 2>/dev/null
fi
sleep 1

# Activate the virtual environment
source venv/bin/activate

# Start FastAPI server in the background and capture its PID
echo "-> Starting Python server..."
uvicorn main:app --reload &
SERVER_PID=$!

# Wait for the server to be up before starting ngrok
echo "-> Waiting for server to start..."
sleep 3

# Check the server actually started successfully
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo ""
    echo "❌ ERROR: Server failed to start! Check the error above."
    exit 1
fi

echo "-> Server is up! Starting ngrok tunnel..."
echo ""
echo "📌 Copy your ngrok URL and paste it into Meta's Webhook settings."
echo "   Press CTRL+C to stop everything."
echo ""

# Start ngrok in the foreground
ngrok http 8000

# When CTRL+C stops ngrok, this cleans up the Python server too
echo ""
echo "-> Stopping server (PID: $SERVER_PID)..."
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
echo "✅ Server shut down cleanly."
