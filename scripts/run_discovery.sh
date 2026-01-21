#!/bin/bash
# Run API discovery script to analyze BSA Online portal

cd "$(dirname "$0")/.."

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate
pip install -q playwright rich

# Install playwright browsers
playwright install chromium

# Run discovery
echo "Starting API discovery..."
python discover_api.py
