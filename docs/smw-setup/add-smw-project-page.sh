#!/bin/bash
# Adds the SMW Setup project page and article to the NanoClaw wiki

WIKI_URL="http://localhost:8080"
USER="Admin"
PASS="AdminPass123!"

# Helper function to create/update a wiki page via the API
create_page() {
  local TITLE="$1"
  local CONTENT="$2"

  # Get login token
  LOGIN_TOKEN=$(curl -s "${WIKI_URL}/api.php?action=query&meta=tokens&type=login&format=json" \
    -c /tmp/smw_cookies.txt | python3 -c "import sys,json; print(json.load(sys.stdin)['query']['tokens']['logintoken'])")

  # Login
  curl -s -c /tmp/smw_cookies.txt -b /tmp/smw_cookies.txt \
    "${WIKI_URL}/api.php" \
    --data-urlencode "action=login" \
    --data-urlencode "lgname=${USER}" \
    --data-urlencode "lgpassword=${PASS}" \
    --data-urlencode "lgtoken=${LOGIN_TOKEN}" \
    --data-urlencode "format=json" > /dev/null

  # Get CSRF token
  CSRF_TOKEN=$(curl -s -c /tmp/smw_cookies.txt -b /tmp/smw_cookies.txt \
    "${WIKI_URL}/api.php?action=query&meta=tokens&format=json" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['query']['tokens']['csrftoken'])")

  # Create the page
  RESULT=$(curl -s -c /tmp/smw_cookies.txt -b /tmp/smw_cookies.txt \
    "${WIKI_URL}/api.php" \
    --data-urlencode "action=edit" \
    --data-urlencode "title=${TITLE}" \
    --data-urlencode "text=${CONTENT}" \
    --data-urlencode "token=${CSRF_TOKEN}" \
    --data-urlencode "format=json")

  echo "  → ${TITLE}: $(echo $RESULT | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('edit',{}).get('result','ERROR: '+str(d)))")"
}

echo "=== Adding SMW Setup Project Pages ==="

create_page "Project:SMW Setup" "{{Project
|name=SemanticMediaWiki Setup
|status=Completed
|start_date=April 4, 2026
|owner=javastarchild
|description=Self-hosted SemanticMediaWiki 6.0 instance running in Docker as the NanoClaw knowledge base. Stores all projects, issues, and predictions as interlinked semantic pages with live query tables.
}}

== Overview ==
MediaWiki 1.43 + SemanticMediaWiki 6.0 running in Docker on the home lab server (GA-78LMT-S2P, Ubuntu 24.04). The wiki serves as a living knowledge graph for all NanoClaw projects.

[[Has property::Stack | MediaWiki 1.43, SMW 6.0, MariaDB 10.11, Docker]]
[[Has property::URL | http://localhost:8080]]

== Setup Files ==
All setup files are in the [[Project:Stock Picker]] repo at <code>docs/smw-setup/</code>:
* <code>Dockerfile</code> — Custom mediawiki image with SMW baked in at build time
* <code>docker-compose.yml</code> — Orchestrates DB + wiki containers
* <code>LocalSettings.php</code> — MediaWiki config with SMW, custom namespaces
* <code>setup.sh</code> — One-command installer
* <code>bootstrap-pages.sh</code> — Seeds initial wiki content

== Issues Encountered ==

=== Issue 1: setup.sh cp failure ===
<code>cp: cannot stat './docker-compose.yml': No such file or directory</code>

Script changed directory before capturing its own location. Fixed by capturing <code>SCRIPT_DIR=\$(cd \"\$(dirname \"\$0\")\" && pwd)</code> before the <code>cd</code>.

=== Issue 2: docker-compose-plugin not available ===
<code>E: Unable to locate package docker-compose-plugin</code>

Package only exists in Docker's official apt repo, not Ubuntu's default repos. Fixed by adding Docker's apt repo manually.

=== Issue 3: SMW extension missing during install ===
<code>Unable to open file .../SemanticMediaWiki/extension.json</code>

MediaWiki installer loads LocalSettings.php immediately, which referenced SMW before it was installed. Fixed by baking SMW into a custom Dockerfile via Composer at build time.

=== Issue 4: composer.json permission denied (uid=1000 lock) ===
<code>file_put_contents(./composer.json): Failed to open stream: Permission denied</code>

The <code>mediawiki:1.43</code> image ships files owned by uid=1000 (CI build user). Docker on this system drops CAP_DAC_OVERRIDE, so even root cannot write to uid=1000 files. Root CAN create new files in the world-writable directory.

Fixed by deleting the uid=1000 file and replacing with a root-owned copy in the Dockerfile:
<pre>
RUN cp /var/www/html/composer.json /tmp/composer.json \
    && rm /var/www/html/composer.json \
    && cp /tmp/composer.json /var/www/html/composer.json \
    && composer require mediawiki/semantic-media-wiki:'^6.0' ...
</pre>

=== Issue 5: LocalSettings.php became a directory ===
When LocalSettings.php was temporarily moved aside, Docker created an empty directory in its place to satisfy the bind mount. Fixed by using <code>docker run --network</code> directly for the installer step (bypasses Compose volume mounts entirely).

== Key Lessons ==
# Use <code>docker run</code> (not <code>docker compose run</code>) for the MediaWiki installer
# SMW must be in the image before installer runs — Dockerfile is the right place
# The uid=1000 write-block is the core challenge with mediawiki:1.43
# Docker creates directories for missing bind-mount sources — watch for this

== Full Article ==
See [[Article:SMW Setup Journey]] for the complete write-up.

[[Category:Projects]]
[[Category:Completed]]
[[Category:Infrastructure]]"

create_page "Article:SMW Setup Journey" "$(cat /workspace/extra/stock_picker/docs/smw-setup-article.md 2>/dev/null | sed 's/|/{{!}}/g' || echo 'Article file not found — see docs/smw-setup-article.md in the stock_picker repo.')"

rm -f /tmp/smw_cookies.txt
echo ""
echo "=== Done! Pages added to wiki ==="
echo "  Project:SMW Setup   → http://localhost:8080/wiki/Project:SMW_Setup"
echo "  Article:SMW Setup   → http://localhost:8080/wiki/Article:SMW_Setup_Journey"
