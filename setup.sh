#!/bin/bash
# Quick setup script for Water Bill Bot

set -e

echo "=== Water Bill Bot Setup ==="

# Check Python version
python3 --version || { echo "Python 3 required"; exit 1; }

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium

# Create .env if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  Please edit .env with your credentials:"
    echo "   - TELEGRAM_BOT_TOKEN"
    echo "   - DATABASE_URL"
    echo "   - BSA_USERNAME / BSA_PASSWORD (optional)"
    echo ""
fi

# Create directories
mkdir -p screenshots discovery_results

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit .env with your configuration"
echo "2. Run API discovery: python discover_api.py"
echo "3. Initialize database: python scripts/init_db.py"
echo "4. Start the bot: python main.py"
