#!/bin/bash

# Local testing script for Benzinga scraper
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🧪 Testing Benzinga Scraper Locally${NC}"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${RED}❌ .env file not found. Copy .env.example to .env and configure it.${NC}"
    exit 1
fi

# Load environment variables
source .env

# Check if benzinga-addon exists
if [ ! -d benzinga-addon ]; then
    echo -e "${YELLOW}⚠️  benzinga-addon not found. Copying from parent directory...${NC}"
    if [ -d ../benzinga-addon ]; then
        cp -r ../benzinga-addon ./
        echo -e "${GREEN}✓ Extension copied${NC}"
    else
        echo -e "${RED}❌ benzinga-addon not found. Please copy it to this directory.${NC}"
        exit 1
    fi
fi

# Install dependencies
if [ ! -d node_modules ]; then
    echo -e "${GREEN}📦 Installing dependencies...${NC}"
    npm install
fi

# Check if Docker is running (optional, for container testing)
if command -v docker &> /dev/null && docker info &> /dev/null; then
    echo -e "${GREEN}🐳 Docker detected. You can test with Docker:${NC}"
    echo "  docker build -t benzinga-test ."
    echo "  docker run -p 8080:8080 --env-file .env benzinga-test"
    echo ""
fi

# Start the app locally
echo -e "${GREEN}🚀 Starting scraper locally on port 8080...${NC}"
echo ""
echo -e "${GREEN}Health check:${NC} http://localhost:8080"
echo -e "${GREEN}Manual scrape:${NC} http://localhost:8080/scrape"
echo -e "${GREEN}View news:${NC} http://localhost:8080/news"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

npm start
