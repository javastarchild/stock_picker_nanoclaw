# GitHub Auto-Save: Token Injection Setup

The nightly auto-save task runs at 11 PM ET but **push fails** because:
1. `gh` CLI is not available inside the NanoClaw container
2. No GitHub token is injected into the container environment
3. `nanoclaw-state` (`~/`) is not mounted in the container

This doc covers the two-part fix.

---

## Part 1 — Inject a GitHub Token into the Container

### Option A: Environment Variable via NanoClaw container_config (Recommended)

Edit the `registered_groups` table in `~/nanoclaw/store/messages.db` and add a `GITHUB_TOKEN` env var to the container config for the main group.

**Step 1: Generate a GitHub Personal Access Token**
1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Scopes needed: `repo` (full)
4. Set expiration as desired (no expiry for automation, or 1 year)
5. Copy the token: `ghp_xxxxxxxxxxxx`

**Step 2: Add token to container env via SQLite**
```bash
cd ~/nanoclaw

node -e "
const Database = require('better-sqlite3');
const db = new Database('store/messages.db');

// Get current config for the main group
const row = db.prepare(\"SELECT jid, container_config FROM registered_groups WHERE name = 'Main'\").get();
const config = JSON.parse(row.container_config || '{}');

// Add environment variable
config.env = config.env || {};
config.env.GITHUB_TOKEN = 'ghp_YOUR_TOKEN_HERE';

db.prepare(\"UPDATE registered_groups SET container_config = ? WHERE jid = ?\")
  .run(JSON.stringify(config), row.jid);

console.log('Updated:', JSON.stringify(config, null, 2));
db.close();
"
```

**Step 3: Restart NanoClaw to pick up the new env**
```bash
systemctl --user restart nanoclaw
```

**Step 4: Verify the token is accessible in the container**
The auto-save task can then use:
```bash
git remote set-url origin https://javastarchild:${GITHUB_TOKEN}@github.com/javastarchild/stock_picker_nanoclaw.git
```

---

## Part 2 — Mount nanoclaw-state in the Container

`nanoclaw-state` lives at `~/nanoclaw-state` on the host but is not mounted in the container workspace. The nightly task can't commit/push it from within the container.

### Fix: Add additionalMount via SQLite

```bash
cd ~/nanoclaw

node -e "
const Database = require('better-sqlite3');
const db = new Database('store/messages.db');

const row = db.prepare(\"SELECT jid, container_config FROM registered_groups WHERE name = 'Main'\").get();
const config = JSON.parse(row.container_config || '{}');

// Add nanoclaw-state mount
config.additionalMounts = config.additionalMounts || [];
const alreadyMounted = config.additionalMounts.some(m => m.hostPath && m.hostPath.includes('nanoclaw-state'));
if (!alreadyMounted) {
  config.additionalMounts.push({
    hostPath: '/home/javastarchild/nanoclaw-state',
    containerPath: '/workspace/extra/nanoclaw-state',
    readonly: false
  });
}

db.prepare(\"UPDATE registered_groups SET container_config = ? WHERE jid = ?\")
  .run(JSON.stringify(config), row.jid);

console.log('Updated mounts:', JSON.stringify(config.additionalMounts, null, 2));
db.close();
"
```

Then restart NanoClaw:
```bash
systemctl --user restart nanoclaw
```

---

## Part 3 — Updated Auto-Save Task Logic

Once token + mount are in place, update the nightly task prompt to use `GITHUB_TOKEN`:

```bash
# Set authenticated remotes
cd /workspace/extra/stock_picker
git remote set-url origin https://javastarchild:${GITHUB_TOKEN}@github.com/javastarchild/stock_picker_nanoclaw.git

cd /workspace/extra/nanoclaw-state
git remote set-url origin https://javastarchild:${GITHUB_TOKEN}@github.com/javastarchild/nanoclaw-state.git

# Sync reports
mkdir -p /workspace/extra/nanoclaw-state/reports
cp /workspace/extra/stock_picker/report/*.csv /workspace/extra/nanoclaw-state/reports/ 2>/dev/null || true
cp /workspace/extra/stock_picker/report/*.txt /workspace/extra/nanoclaw-state/reports/ 2>/dev/null || true

# Commit and push nanoclaw-state
cd /workspace/extra/nanoclaw-state
git add .
git diff --cached --quiet || git commit -m "Auto-save state $(date '+%Y-%m-%d')"
git push origin master 2>/dev/null || git push origin main 2>/dev/null || true

# Commit and push stock_picker
cd /workspace/extra/stock_picker
git add report/ docs/ 2>/dev/null || true
git diff --cached --quiet || git commit -m "Auto-save reports $(date '+%Y-%m-%d')"
git push origin master 2>/dev/null || git push origin main 2>/dev/null || true
```

---

## Current Status (as of 2026-04-08)

| Item | Status |
|------|--------|
| GITHUB_TOKEN in container env | ❌ Not set |
| nanoclaw-state mounted in container | ❌ Not mounted |
| stock_picker mounted in container | ✅ `/workspace/extra/stock_picker` |
| Nightly task scheduled | ✅ 11 PM ET |
| Local commits being made | ✅ (stack up without push) |
| Pushes succeeding | ❌ Auth failure |

**Action needed from host:** Run Part 1 + Part 2 steps above, then restart NanoClaw.
