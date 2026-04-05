#!/bin/bash
# Usage: wiki-publish.sh "Page:Title" /path/to/file.md
# Publishes a local file to the NanoClaw wiki
#
# Examples:
#   wiki-publish.sh "Article:SMW Setup Journey" ~/stock_picker/docs/smw-setup-article.md
#   wiki-publish.sh "Project:My New Project" ~/stock_picker/docs/my-project.md

set -e

WIKI="${WIKI_URL:-http://localhost:8080}"
USER="${WIKI_USER:-Admin}"
PASS="${WIKI_PASS:-AdminPass123!}"
TITLE="$1"
FILE="$2"

if [[ -z "$TITLE" || -z "$FILE" ]]; then
  echo "Usage: $0 \"Page:Title\" /path/to/file.md"
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "Error: file not found: $FILE"
  exit 1
fi

COOKIES=$(mktemp /tmp/wiki_cookies_XXXXXX.txt)
trap "rm -f $COOKIES" EXIT

# Login token
TOKEN=$(curl -s "${WIKI}/api.php?action=query&meta=tokens&type=login&format=json" \
  -c "$COOKIES" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['query']['tokens']['logintoken'])")

# Login
curl -s -c "$COOKIES" -b "$COOKIES" "${WIKI}/api.php" \
  -d "action=login&lgname=${USER}&format=json" \
  --data-urlencode "lgpassword=${PASS}" \
  --data-urlencode "lgtoken=${TOKEN}" > /dev/null

# CSRF token
CSRF=$(curl -s -c "$COOKIES" -b "$COOKIES" \
  "${WIKI}/api.php?action=query&meta=tokens&format=json" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['query']['tokens']['csrftoken'])")

# Publish
CONTENT=$(cat "$FILE")
RESULT=$(curl -s -c "$COOKIES" -b "$COOKIES" "${WIKI}/api.php" \
  -d "action=edit&format=json" \
  --data-urlencode "title=${TITLE}" \
  --data-urlencode "text=<pre>${CONTENT}</pre>" \
  --data-urlencode "token=${CSRF}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('edit',{}).get('result','ERROR: '+str(d)))")

echo "${RESULT}: ${TITLE}"
echo "→ ${WIKI}/wiki/$(echo "$TITLE" | sed 's/ /_/g')"
