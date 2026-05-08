#!/usr/bin/env bash
echo "Stopping Donut Intel Platform..."
pkill -f "uvicorn backend.app:app" 2>/dev/null && echo "Stopped." || echo "No running instance found."
