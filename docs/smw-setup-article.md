# Standing Up SemanticMediaWiki on a Home Linux Machine: Every Error and How We Fixed It

*By javastarchild | April 2026*

---

## The Goal

Add a self-hosted [SemanticMediaWiki](https://www.semantic-mediawiki.org/) (SMW) instance to the NanoClaw home lab — a living knowledge graph that auto-populates tables of projects, issues, and predictions using semantic properties stored directly in wiki pages.

**Stack**: MediaWiki 1.43 + SemanticMediaWiki 6.0 + MariaDB 10.11, running in Docker on Ubuntu 24.04 (GA-78LMT-S2P).

---

## Architecture

Three Docker containers managed by a single `docker-compose.yml`:

| Container | Image | Role |
|-----------|-------|------|
| `smw-wiki` | `smw-mediawiki:1.43` (custom build) | Apache + PHP + MediaWiki + SMW |
| `smw-db` | `mariadb:10.11` | Database |

**Key insight**: SMW is installed via Composer *at image build time* inside a custom `Dockerfile` extending `mediawiki:1.43`. This avoids runtime permission issues and ensures extensions survive container restarts.

---

## Setup Files

All setup files live in the `stock_picker` repo at `docs/smw-setup/`:

```
docs/smw-setup/
├── Dockerfile           # Custom mediawiki image with SMW baked in
├── docker-compose.yml   # DB + wiki services
├── LocalSettings.php    # MediaWiki config with SMW enabled
├── setup.sh             # One-command installer
└── bootstrap-pages.sh   # Seeds initial wiki content
```

---

## Installation Steps (the correct sequence)

```bash
# 1. Clone/pull the stock_picker repo to get the setup files
cd ~/stock_picker/docs/smw-setup

# 2. Install docker-compose-plugin (not in default Ubuntu repos)
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y docker-compose-plugin

# 3. Create the wiki directory and copy setup files
mkdir -p ~/nanoclaw-wiki
cp docker-compose.yml ~/nanoclaw-wiki/
cp Dockerfile ~/nanoclaw-wiki/
cp LocalSettings.php ~/nanoclaw-wiki/

# 4. Build the custom image (installs SMW via Composer — takes 5-10 min)
cd ~/nanoclaw-wiki
docker compose build

# 5. Start the database
docker compose up -d db
sleep 15  # wait for MariaDB to initialize

# 6. Run MediaWiki installer (using docker run directly — NOT docker compose run)
docker run --rm \
  --network nanoclaw-wiki_default \
  smw-mediawiki:1.43 \
  php maintenance/install.php \
    --dbserver=db --dbname=mediawiki \
    --dbuser=wikiuser --dbpass=wikipass \
    --server="http://localhost:8080" \
    --scriptpath="" --lang=en \
    --pass=AdminPass123! \
    "NanoClaw Knowledge Base" "Admin"

# 7. Start everything
docker compose up -d

# 8. Initialize SMW semantic store
sleep 5
docker compose exec mediawiki php maintenance/update.php --quick
docker compose exec mediawiki php extensions/SemanticMediaWiki/maintenance/setupStore.php

# 9. Bootstrap initial pages
bash ~/stock_picker/docs/smw-setup/bootstrap-pages.sh
```

Visit **http://localhost:8080** — login with Admin / AdminPass123! (change this immediately).

---

## Every Error We Hit and How We Fixed It

### Error 1: `cp: cannot stat './docker-compose.yml': No such file or directory`

**Cause**: `setup.sh` changed directories to `~/nanoclaw-wiki` before capturing the script's own location. `$(dirname "$0")` then resolved relative to the new working directory, not the script's directory.

**Fix**: Capture `SCRIPT_DIR` before `cd`:
```bash
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WIKI_DIR="$HOME/nanoclaw-wiki"
mkdir -p "$WIKI_DIR"
cd "$WIKI_DIR"
cp "$SCRIPT_DIR/docker-compose.yml" .
```

---

### Error 2: `docker: unknown command: docker compose`

**Cause**: Docker was installed via the convenience script (`get.docker.com`) but the `docker-compose-plugin` package wasn't pulled in. The plugin lives in Docker's own apt repo, not Ubuntu's default repos.

**Fix**: Add Docker's official apt repo and install from there:
```bash
sudo apt-get install -y docker-compose-plugin
# (after adding Docker's apt repo — see full steps above)
```

---

### Error 3: `Unable to open file /var/www/html/extensions/SemanticMediaWiki/extension.json`

**Cause**: `LocalSettings.php` referenced `wfLoadExtension('SemanticMediaWiki')` but the extension wasn't installed yet. The MediaWiki installer loads `LocalSettings.php` during setup and immediately crashes.

**Fix**: SMW must be installed *before* the MediaWiki installer runs. The solution is to bake SMW into a custom Docker image (Dockerfile) so it's present before any container starts.

---

### Error 4: `file_put_contents(./composer.json): Failed to open stream: Permission denied`

**Root cause (after extensive diagnosis)**: The `mediawiki:1.43` image has `/var/www/html/` owned by `www-data:www-data` (drwxrwxrwt), but all files *inside* it (including `composer.json`) are owned by `uid=1000` with mode `664`. Docker on this system drops `CAP_DAC_OVERRIDE`, meaning even root inside the container cannot write to files owned by another user.

This manifested in three different contexts:
- Separate `composer` Docker Compose service (even with `user: root`)
- `docker exec -u root` into the running container
- `docker build` RUN steps (even with `USER root` in Dockerfile)

**Diagnosis command that revealed it**:
```bash
docker run --rm mediawiki:1.43 bash -c "
  id &&
  ls -la /var/www/html/composer.json &&
  echo test >> /var/www/html/composer.json && echo 'WRITE OK' || echo 'WRITE FAILED'
"
# uid=0(root) ... -rw-rw-r-- 1 1000 1000 ... WRITE FAILED
```

**Key finding**: Root CAN create *new* files in `/var/www/html/` (directory is world-writable), but CANNOT write to *existing* files owned by uid=1000.

**Fix**: In the Dockerfile, delete the uid=1000-owned `composer.json` and replace it with a root-owned copy before running Composer:
```dockerfile
FROM mediawiki:1.43
USER root
RUN cp /var/www/html/composer.json /tmp/composer.json \
    && rm /var/www/html/composer.json \
    && cp /tmp/composer.json /var/www/html/composer.json \
    && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && composer require \
        mediawiki/semantic-media-wiki:'^6.0' \
        mediawiki/semantic-result-formats:'^5.0' \
        --working-dir=/var/www/html --no-interaction
```

---

### Error 5: `LocalSettings.php` becomes a directory

**Cause**: `docker compose run` mounts `./LocalSettings.php` as a bind volume. When we temporarily moved the file away (so the installer would run), Docker found a missing bind-mount source and created an empty *directory* named `LocalSettings.php` in its place. Owned by root, it blocked all subsequent attempts to restore the file.

**Symptoms**:
```
mv: cannot move 'LocalSettings.php.smw' to 'LocalSettings.php/LocalSettings.php.smw': Permission denied
drwxr-xr-x  2 root root  LocalSettings.php   ← directory, not file!
```

**Fix**: Remove the rogue directory with sudo, then use `docker run` directly (no Compose, no volume mounts) for the installer step:
```bash
sudo rm -rf ~/nanoclaw-wiki/LocalSettings.php
docker run --rm --network nanoclaw-wiki_default smw-mediawiki:1.43 \
  php maintenance/install.php ...
```

---

## Lessons Learned

1. **Always use `docker run` (not `docker compose run`) for the MediaWiki installer** — Compose mounts your LocalSettings.php, which the installer refuses to overwrite.

2. **SMW must be in the image before the installer runs** — the only clean approach is a custom Dockerfile that runs Composer at build time.

3. **The uid=1000 write-block is the core challenge** — the mediawiki:1.43 image ships files owned by the Docker Hub CI build user (uid=1000). On systems where Docker drops CAP_DAC_OVERRIDE, even root can't write to these files. The workaround: `rm` the original (allowed because the directory is world-writable) then `cp` a root-owned replacement.

4. **Docker creates directories for missing bind-mount sources** — if you move a file that's listed in a volume mount, Docker will create an empty directory in its place. Always use `docker run --network <project_network>` when you need to run a container without Compose's volume mounts.

---

## Maintenance

The wiki runs automatically and survives reboots (`restart: unless-stopped`). The database is persisted in the `wiki-db` Docker volume.

To stop: `docker compose -f ~/nanoclaw-wiki/docker-compose.yml stop`
To start: `docker compose -f ~/nanoclaw-wiki/docker-compose.yml start`
To rebuild after config changes: `docker compose -f ~/nanoclaw-wiki/docker-compose.yml build && docker compose up -d`

---

*Setup completed April 4, 2026 in collaboration with Andy (Claude, Anthropic).*
