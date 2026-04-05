#!/bin/bash
# =========================================================
# NanoClaw SMW Setup Script
# Run this on your Linux machine (javastarchild-GA-78LMT-S2P)
# =========================================================

set -e

echo "=== NanoClaw Knowledge Base Setup ==="
echo ""

# Step 1: Check Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

if ! command -v docker compose &> /dev/null; then
    echo "Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

echo "✅ Docker ready: $(docker --version)"
echo ""

# Step 2: Create working directory
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WIKI_DIR="$HOME/nanoclaw-wiki"
mkdir -p "$WIKI_DIR"
cd "$WIKI_DIR"

echo "📁 Working directory: $WIKI_DIR"
echo ""

# Step 3: Copy config files
cp "$SCRIPT_DIR/docker-compose.yml" .
cp "$SCRIPT_DIR/LocalSettings.php" .

# Step 4: Generate secret keys
SECRET_KEY=$(openssl rand -hex 32)
UPGRADE_KEY=$(openssl rand -hex 8)
sed -i "s/CHANGE_ME_generate_with_openssl_rand_hex_32/$SECRET_KEY/" LocalSettings.php
sed -i "s/CHANGE_ME_generate_with_openssl_rand_hex_8/$UPGRADE_KEY/" LocalSettings.php

echo "🔑 Secret keys generated"
echo ""

# Step 5: Start database first
echo "🗄️  Starting database..."
docker compose up -d db
echo "Waiting for database to be ready..."
sleep 15

# Step 6: Run MediaWiki installer
echo "🔧 Running MediaWiki installer..."
docker compose run --rm mediawiki php maintenance/install.php \
    --dbserver=db \
    --dbname=mediawiki \
    --dbuser=wikiuser \
    --dbpass=wikipass \
    --server="http://localhost:8080" \
    --scriptpath="" \
    --lang=en \
    --pass=AdminPass123! \
    "NanoClaw Knowledge Base" \
    "Admin"

# Step 7: Start everything
echo "🚀 Starting wiki..."
docker compose up -d

# Step 8: Run SMW setup
echo "⚙️  Setting up SemanticMediaWiki store..."
sleep 5
docker compose exec mediawiki php maintenance/update.php --quick
docker compose exec mediawiki php extensions/SemanticMediaWiki/maintenance/setupStore.php

echo ""
echo "=========================================="
echo "✅ NanoClaw Knowledge Base is READY!"
echo "=========================================="
echo ""
echo "  🌐 URL:      http://localhost:8080"
echo "  👤 Username: Admin"
echo "  🔑 Password: AdminPass123!"
echo ""
echo "  ⚠️  Change the admin password after first login!"
echo ""
echo "Next: Run bootstrap-pages.sh to create the project pages"
