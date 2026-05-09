#!/usr/bin/env bash
echo "Stopping Donut Intel Platform..."
pkill -f "uvicorn backend.app:app" 2>/dev/null && echo "Stopped." || echo "No running instance found."
pkill -f "chrome-headless-shell" 2>/dev/null
pkill -f "playwright/driver/node" 2>/dev/null
