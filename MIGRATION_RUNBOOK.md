# Migration Runbook — Apps to New Prod Droplet

_Option B: apps move to new prod droplet; Claude + orchestration stay on current (dev) droplet. Existing URLs preserved via nginx reverse-proxy on dev. Claude chats, bookmarks, watchdog — all unchanged._

_Author: infra orchestrator. Written: 2026-04-16._

---

## The pattern every project follows

For each app, we do these steps in order. **The URL never changes from the user's perspective** because dev's nginx keeps serving the same path — it just reverse-proxies requests through to prod.

1. Install deps on prod.
2. Rsync code + data from dev.
3. Copy systemd unit files; start services on prod.
4. Verify prod serves correctly via the private IP.
5. Flip dev nginx from "serve locally" to "proxy to prod."
6. Run `projects-smoketest.sh gate` — confirm no regression.
7. Stop local services on dev (don't delete files yet).
8. After 24h stable, delete local copies.

If anything breaks: **revert nginx on dev** (30-second undo). User-visible URL resumes serving from the still-intact dev copy.

---

## Phase 0 — Prep (one-time, before any app moves)

### 0.1 User actions on DigitalOcean

You do these; I can't. Ping me when done, with the new droplet's public + private IPs.

1. **Create new droplet** in DO console:
   - Size: **`s-4vcpu-16gb-intel` Premium Intel** (~$96/mo). Reason: doubles current cores, 4× RAM, enough for all apps + multi-browser work with room to grow.
   - Region: **same region as current droplet** (whichever NYC/SFO — matches the existing droplet). Required for free private networking.
   - OS: **Ubuntu 22.04 LTS** (same as dev, so our deploy scripts translate 1:1).
   - **Enable VPC / private networking** (free, ~1 ms latency between droplets).
   - **Enable weekly backups** (20% of droplet cost; ~$20/mo; worth it for prod).
   - SSH keys: check **both** your personal key AND the one labeled "Claude orchestrator (dev droplet)" — both allow you (from laptop) and me (from dev) to SSH in.
   - Hostname: **`casinv-prod`** (or whatever you prefer; appears in prompts + logs).

2. **After the droplet boots, paste me:**
   - Public IP (e.g., `159.223.1.X`)
   - Private IP (from DO console → droplet → Networking tab, usually `10.X.Y.Z`)

### 0.2 Infra-agent actions (I do these after you give me the IPs)

```bash
# Sanity: can I SSH?
ssh -o StrictHostKeyChecking=accept-new root@<PROD_PUBLIC_IP> hostname
# Should print: casinv-prod

# Bootstrap: install base packages, nginx, certbot, node, python, gnu tools, common libs
ssh root@<PROD_PUBLIC_IP> 'apt-get update -q && apt-get install -y \
    nginx certbot python3-certbot-nginx \
    python3 python3-pip python3-venv \
    nodejs npm \
    git rsync jq curl wget \
    xvfb \
    logrotate \
    linux-modules-extra-$(uname -r)'

# Create /opt/site-deploy clone on prod so shared helpers are available
ssh root@<PROD_PUBLIC_IP> 'git clone https://github.com/csosin1/ClaudeCode.git /opt/site-deploy'

# Set up private-network SSH shortcut from dev
# (so we can rsync via private IP — faster, off the public internet)
echo "Host prod-private
    HostName <PROD_PRIVATE_IP>
    User root
    StrictHostKeyChecking accept-new" >> /root/.ssh/config

# Smoketest from prod: confirm it has internet + DNS
ssh root@<PROD_PUBLIC_IP> 'curl -sf https://casinv.dev/projects.html | head -1'
```

### 0.3 Infra-agent actions, continued

I'll commit a small shim to handle the reverse-proxy pattern. Only touches dev's nginx config — no app moves yet.

```bash
# Test nginx proxy_pass template — run on dev
cat > /tmp/proxy-test.conf <<EOF
location /proxy-test/ {
    proxy_pass http://prod-private/timeshare-surveillance/;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
EOF
# Don't actually install until we have prod serving something
```

### 0.4 Firewall bake-in (mandatory — learned 2026-04-17)

DO ships Ubuntu images with ufw **inactive**. Any future app that binds 0.0.0.0 will be publicly reachable on the prod droplet's public IP. Close this at the network boundary before any app migrates.

```bash
ssh prod-private 'bash -s' <<'SCRIPT'
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "ssh"
ufw allow 80/tcp comment "nginx"
ufw allow 443/tcp comment "nginx-tls"
ufw allow from 10.116.0.0/20 comment "DO VPC NYC1"
ufw --force enable
ufw status verbose
SCRIPT
```

Verify from dev:
- `curl --max-time 5 http://<PROD_PUBLIC_IP>:<APP_PORT>/` → `HTTP 000` (deny-filtered)
- `curl http://<PROD_PRIVATE_IP>:<APP_PORT>/` → `HTTP 200` (VPC-allow passes)

After 0.2–0.4 pass: **CHECKPOINT 0**. Prod droplet is reachable + bootstrapped + firewalled + we have rsync-ready private IP. Say "proceed to Phase 1" to move on.

---

## Phase 1 — Timeshare Surveillance (the pilot, ~30 min)

**Why first:** smallest footprint (~140 MB), fully audited, narrow interface. If the migration mechanism has a bug, we discover it on the least-important project. **Disk move: trivial.**

### 1.1 Pre-flight

```bash
# From dev: confirm the current state is healthy
curl -sf https://casinv.dev/timeshare-surveillance/ | grep -q 'Timeshare' && echo "LIVE OK"
curl -sf https://casinv.dev/timeshare-surveillance/preview/ | head -c 200

# Check inventory file the timeshare chat produced
cat /opt/site-deploy/helpers/migration-inventory-timeshare-dashboard.md | head -50

# Pause the preview watcher briefly so we have a consistent rsync snapshot
# (live watcher stays running; we migrate preview first)
systemctl stop timeshare-surveillance-watcher-preview
systemctl stop timeshare-surveillance-admin-preview
```

### 1.2 Rsync code + data to prod

```bash
# Create parallel dir structure on prod
ssh prod-private 'mkdir -p /opt/timeshare-surveillance-preview /opt/timeshare-surveillance-live /var/log/timeshare-surveillance'

# Rsync preview first (the one we just paused)
rsync -avz --delete /opt/timeshare-surveillance-preview/ prod-private:/opt/timeshare-surveillance-preview/
# Rsync live (data in motion but small; re-rsync later if drift)
rsync -avz --delete /opt/timeshare-surveillance-live/ prod-private:/opt/timeshare-surveillance-live/

# Env files (contain real creds) — separate scp so we know exactly what moved
scp /opt/timeshare-surveillance-preview/.env prod-private:/opt/timeshare-surveillance-preview/.env
scp /opt/timeshare-surveillance-live/.env prod-private:/opt/timeshare-surveillance-live/.env

# Python venv isn't portable — recreate on prod
ssh prod-private 'cd /opt/timeshare-surveillance-preview && python3 -m venv venv && venv/bin/pip install -r pipeline/requirements.txt admin/requirements.txt 2>/dev/null'
ssh prod-private 'cd /opt/timeshare-surveillance-live && python3 -m venv venv && venv/bin/pip install -r pipeline/requirements.txt admin/requirements.txt 2>/dev/null'
```

### 1.3 Copy systemd units + start on prod

```bash
# Copy the 4 unit files
for u in timeshare-surveillance-watcher timeshare-surveillance-watcher-preview timeshare-surveillance-admin timeshare-surveillance-admin-preview; do
    scp /etc/systemd/system/$u.service prod-private:/etc/systemd/system/$u.service
done
ssh prod-private 'systemctl daemon-reload'

# Start on prod
ssh prod-private 'systemctl enable --now timeshare-surveillance-watcher timeshare-surveillance-watcher-preview timeshare-surveillance-admin timeshare-surveillance-admin-preview'

# Wait a moment, confirm they're healthy
sleep 5
ssh prod-private 'systemctl status timeshare-surveillance-admin --no-pager | head -5'
```

### 1.4 Verify prod serves directly (before flipping nginx)

```bash
# Prod's admin service is on port 8510/8511 — hit it via private IP
ssh prod-private 'curl -sf http://127.0.0.1:8511/admin/ | head -c 200'  # preview
ssh prod-private 'curl -sf http://127.0.0.1:8510/admin/ | head -c 200'  # live

# Dashboard (static HTML served by nginx on prod)
ssh prod-private 'nginx -t'  # make sure nginx config is valid even though we haven't configured project location yet
```

### 1.5 Flip dev nginx to proxy

On dev, edit `/etc/nginx/sites-available/abs-dashboard`. Replace the `location /timeshare-surveillance/` and `location /timeshare-surveillance/preview/` blocks to proxy to prod:

```nginx
location /timeshare-surveillance/preview/ {
    proxy_pass http://<PROD_PRIVATE_IP>:8511/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /timeshare-surveillance/ {
    proxy_pass http://<PROD_PRIVATE_IP>:8510/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

```bash
# Test + reload
nginx -t
systemctl reload nginx

# Smoketest — this is where we confirm nothing broke
/usr/local/bin/projects-smoketest.sh gate
```

### 1.6 Stop local services on dev

Only after Phase 1.5 passes:

```bash
# Keep data intact for rollback; just stop the services
systemctl stop timeshare-surveillance-watcher timeshare-surveillance-watcher-preview timeshare-surveillance-admin timeshare-surveillance-admin-preview
systemctl disable timeshare-surveillance-watcher timeshare-surveillance-watcher-preview timeshare-surveillance-admin timeshare-surveillance-admin-preview
```

### 1.7 Rollback if something breaks

```bash
# Revert nginx — takes 30 seconds
git -C /opt/site-deploy checkout HEAD -- deploy/update_nginx.sh  # if we edited it
# OR manually undo the location blocks
systemctl restart nginx

# Restart local services
systemctl enable --now timeshare-surveillance-watcher timeshare-surveillance-watcher-preview timeshare-surveillance-admin timeshare-surveillance-admin-preview
```

### 1.8 Phase 1 complete checkpoint

- Smoketest passes.
- `curl https://casinv.dev/timeshare-surveillance/` returns the live dashboard (now served by prod).
- `curl https://casinv.dev/timeshare-surveillance/preview/` returns preview (served by prod).
- Admin pages at `/timeshare-surveillance/admin/` load.
- No dev-side services still running for timeshare-surveillance.

**CHECKPOINT 1.** Observe for ~2 hours or overnight. If nothing regresses, proceed to Phase 2.

---

## Phase 2 — Gym Intelligence (~20 min)

**Why next:** simple Flask + JS, ~280 MB total, currently idle. Same pattern as Phase 1 with fewer moving parts.

### 2.1 Pre-flight

```bash
curl -sf https://casinv.dev/gym-intelligence/ | grep -q 'Gym' && echo "LIVE OK"
cat /opt/site-deploy/helpers/migration-inventory-gym-intelligence.md | head -50
```

### 2.2 Rsync

```bash
ssh prod-private 'mkdir -p /opt/gym-intelligence /opt/gym-intelligence-preview /var/log/gym-intelligence'
rsync -avz --delete /opt/gym-intelligence/ prod-private:/opt/gym-intelligence/
rsync -avz --delete /opt/gym-intelligence-preview/ prod-private:/opt/gym-intelligence-preview/
scp /opt/gym-intelligence/.env prod-private:/opt/gym-intelligence/.env 2>/dev/null || true
scp /opt/gym-intelligence-preview/.env prod-private:/opt/gym-intelligence-preview/.env 2>/dev/null || true

# Recreate venvs
ssh prod-private 'cd /opt/gym-intelligence && python3 -m venv venv && venv/bin/pip install -r requirements.txt'
ssh prod-private 'cd /opt/gym-intelligence-preview && python3 -m venv venv && venv/bin/pip install -r requirements.txt'
```

### 2.3 Systemd + start

```bash
for u in gym-intelligence gym-intelligence-preview; do
    scp /etc/systemd/system/$u.service prod-private:/etc/systemd/system/$u.service
done
ssh prod-private 'systemctl daemon-reload && systemctl enable --now gym-intelligence gym-intelligence-preview'
sleep 3
ssh prod-private 'curl -sf http://127.0.0.1:8502/ | head -c 200'  # live
ssh prod-private 'curl -sf http://127.0.0.1:8503/ | head -c 200'  # preview
```

### 2.4 Flip nginx + verify

Replace `location /gym-intelligence/` and `location /gym-intelligence/preview/` in `/etc/nginx/sites-available/abs-dashboard` with proxy_pass pointing at prod's 8502/8503. Reload; smoketest.

### 2.5 Stop local

```bash
systemctl stop gym-intelligence gym-intelligence-preview
systemctl disable gym-intelligence gym-intelligence-preview
```

**CHECKPOINT 2.** Observe briefly. Proceed to Phase 3.

---

## Phase 3 — Carvana Loan Dashboard / abs-dashboard (~2-4 hours)

**Why third:** 34 GB of data to move. This is the big one. Also has the feature-branch-deploy quirk to resolve.

### 3.1 Pre-flight — biggest risk is data integrity

```bash
# Confirm ingestion is NOT running (would cause rsync to miss fresh writes)
ps -ef | grep -iE 'carmax_abs|carvana_abs|run_ingestion' | grep -v grep
# Expected: empty. If anything is running, coordinate with carvana-abs-2 chat to pause.

# Checkpoint the SQLite DBs so they're consistent
for db in /opt/abs-dashboard/carvana_abs/db/*.db /opt/abs-dashboard/carmax_abs/db/*.db; do
    [ -f "$db" ] && sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);"
done

# Inventory size for disk-check on prod
du -sh /opt/abs-dashboard
df -h /opt  # prod needs this much free space
```

### 3.2 Rsync — two passes (initial + delta)

```bash
ssh prod-private 'mkdir -p /opt/abs-dashboard /opt/abs-venv /var/log'

# Pass 1: bulk rsync. Will take 30-60 min for 34 GB over private network.
rsync -avz --delete \
    --exclude='.git/objects/pack/tmp_*' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='static_site/*/docs/*.tmp' \
    /opt/abs-dashboard/ prod-private:/opt/abs-dashboard/

# Python venv (abs-venv is special — big weasyprint deps)
rsync -avz --delete /opt/abs-venv/ prod-private:/opt/abs-venv/
# OR: recreate on prod (safer, ~5 min)
ssh prod-private 'python3 -m venv /opt/abs-venv && /opt/abs-venv/bin/pip install -r /opt/abs-dashboard/carvana_abs/requirements.txt'

# Env file
scp /opt/abs-dashboard/.env prod-private:/opt/abs-dashboard/.env 2>/dev/null || true
```

### 3.3 The feature-branch quirk

`auto_deploy.sh` pulls from `claude/carvana-loan-dashboard-4QMPM` on the abs-dashboard checkout. Two choices:
- **A (preserve quirk):** prod's `/opt/abs-dashboard/` stays on the feature branch. `auto_deploy.sh` runs on prod, pulling the feature branch. Same behavior, just on prod.
- **B (normalize now):** merge feature branch → main, update `auto_deploy.sh` to track main. Cleaner but adds complexity to this migration.

**My recommendation: A for now.** Migrate with the quirk intact; normalize in a separate change after stability is proven. Avoids doing two risky things at once.

```bash
# Keep prod's abs-dashboard on the feature branch, same as dev
ssh prod-private 'cd /opt/abs-dashboard && git checkout claude/carvana-loan-dashboard-4QMPM && git pull'
```

### 3.4 auto_deploy on prod

```bash
# Copy the auto_deploy.sh + timer from dev
scp /opt/auto_deploy.sh prod-private:/opt/auto_deploy.sh
scp /etc/systemd/system/auto-deploy.timer prod-private:/etc/systemd/system/auto-deploy.timer 2>/dev/null
scp /etc/systemd/system/auto-deploy.service prod-private:/etc/systemd/system/auto-deploy.service 2>/dev/null

ssh prod-private 'systemctl daemon-reload && systemctl enable --now auto-deploy.timer'

# Run once manually to confirm it works
ssh prod-private 'bash /opt/auto_deploy.sh'
# Should: pull branch (no-op), run export_dashboard_db, generate static_site, validate
```

### 3.5 Verify prod dashboard serves

```bash
# abs-dashboard serves static files from /opt/abs-dashboard/carvana_abs/static_site/{live,preview}/
# Configure nginx on prod to serve those paths
cat > /tmp/prod-abs.conf <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location /CarvanaLoanDashBoard/preview/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/preview/;
        try_files $uri $uri/ =404;
    }
    location /CarvanaLoanDashBoard/ {
        alias /opt/abs-dashboard/carvana_abs/static_site/live/;
        try_files $uri $uri/ =404;
    }
}
EOF
scp /tmp/prod-abs.conf prod-private:/etc/nginx/sites-available/abs-dashboard-prod
ssh prod-private 'ln -sf /etc/nginx/sites-available/abs-dashboard-prod /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx'

# Test via private IP
ssh prod-private 'curl -sf http://127.0.0.1/CarvanaLoanDashBoard/ | head -c 300'
```

### 3.6 Delta rsync just before the flip (catches any new writes)

```bash
# Right before nginx flip, rsync any delta (normally small; seconds)
rsync -avz --delete /opt/abs-dashboard/carvana_abs/db/ prod-private:/opt/abs-dashboard/carvana_abs/db/
rsync -avz --delete /opt/abs-dashboard/carmax_abs/db/ prod-private:/opt/abs-dashboard/carmax_abs/db/
rsync -avz --delete /opt/abs-dashboard/carvana_abs/static_site/ prod-private:/opt/abs-dashboard/carvana_abs/static_site/
```

### 3.7 Flip nginx + verify

Replace `location /CarvanaLoanDashBoard/` and `location /CarvanaLoanDashBoard/preview/` with:

```nginx
location /CarvanaLoanDashBoard/preview/ {
    proxy_pass http://<PROD_PRIVATE_IP>/CarvanaLoanDashBoard/preview/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
location /CarvanaLoanDashBoard/ {
    proxy_pass http://<PROD_PRIVATE_IP>/CarvanaLoanDashBoard/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

```bash
nginx -t && systemctl reload nginx
/usr/local/bin/projects-smoketest.sh gate
```

### 3.8 Decommission + reclaim disk

```bash
# Stop auto-deploy on dev
systemctl stop auto-deploy.timer
systemctl disable auto-deploy.timer

# After 24h confidence: reclaim the 34 GB
# rm -rf /opt/abs-dashboard
# rm -rf /opt/abs-venv
# Do this only after you're confident the prod serves correctly.
```

**CHECKPOINT 3.** Biggest migration done. The dev droplet disk should drop from 74% to ~40%.

---

## Phase 4 — Car Offers (~1 hour)

**Why last:** still actively iterating + has Playwright/Chrome/Xvfb dependencies. Migrating a moving target adds risk; also benefits from the most headroom on prod.

### 4.1 Pre-flight — let the car-offers chat know

```bash
# Dispatch a prompt: "we're about to migrate car-offers. pause any in-flight Playwright runs; commit/push work; ready for rsync?"
tmux send-keys -t claude:car-offers "MIGRATION: we're about to rsync /opt/car-offers to prod. Pause any active browser runs. Commit + push any uncommitted work. One-line ack when ready." Enter
```

After car-offers chat acks:

```bash
# Pause services (Playwright sessions will die; that's expected)
systemctl stop car-offers car-offers-preview xvfb
pkill -f chromium 2>/dev/null || true
```

### 4.2 Rsync (~1.4 GB, mostly /opt/car-offers-preview/)

```bash
ssh prod-private 'mkdir -p /opt/car-offers /opt/car-offers-preview /opt/car-offers-data /var/log/car-offers'

rsync -avz --delete \
    --exclude='node_modules' --exclude='.chrome-profile' --exclude='*.log' \
    /opt/car-offers/ prod-private:/opt/car-offers/
rsync -avz --delete \
    --exclude='node_modules' --exclude='.chrome-profile' --exclude='*.log' \
    /opt/car-offers-preview/ prod-private:/opt/car-offers-preview/
rsync -avz --delete /opt/car-offers-data/ prod-private:/opt/car-offers-data/

scp /opt/car-offers/.env prod-private:/opt/car-offers/.env
scp /opt/car-offers-preview/.env prod-private:/opt/car-offers-preview/.env

# Reinstall node modules on prod (different arch possible, always recreate)
ssh prod-private 'cd /opt/car-offers && npm ci --quiet'
ssh prod-private 'cd /opt/car-offers-preview && npm ci --quiet'

# Install Playwright's chromium on prod
ssh prod-private 'cd /opt/car-offers && npx playwright install chromium --with-deps'
```

### 4.3 Systemd units (includes Xvfb for headed browser)

```bash
for u in car-offers car-offers-preview xvfb; do
    scp /etc/systemd/system/$u.service prod-private:/etc/systemd/system/$u.service
done
ssh prod-private 'systemctl daemon-reload && systemctl enable --now xvfb && sleep 2 && systemctl enable --now car-offers car-offers-preview'

# Verify
ssh prod-private 'curl -sf http://127.0.0.1:3100/ | head -c 200'  # live
ssh prod-private 'curl -sf http://127.0.0.1:3101/ | head -c 200'  # preview
```

### 4.4 Flip nginx + verify

```nginx
location /car-offers/preview/ {
    proxy_pass http://<PROD_PRIVATE_IP>:3101/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
location /car-offers/ {
    proxy_pass http://<PROD_PRIVATE_IP>:3100/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

```bash
nginx -t && systemctl reload nginx
/usr/local/bin/projects-smoketest.sh gate
```

### 4.5 Decommission

```bash
systemctl stop car-offers car-offers-preview xvfb
systemctl disable car-offers car-offers-preview xvfb
# Keep files for 24h in case of rollback need.
```

**CHECKPOINT 4.** All apps migrated. Dev droplet now only runs Claude + orchestration.

---

## Phase 5 — Post-migration cleanup (~30 min, after 24-48h stable)

### 5.1 Reclaim disk on dev

```bash
# Order of magnitude: frees 34 GB (abs-dashboard) + 180 MB (gym-preview) + 1.4 GB (car-offers-preview) + ~140 MB (timeshare) = ~36 GB
rm -rf /opt/abs-dashboard /opt/abs-venv
rm -rf /opt/gym-intelligence /opt/gym-intelligence-preview
rm -rf /opt/timeshare-surveillance-live /opt/timeshare-surveillance-preview
rm -rf /opt/car-offers /opt/car-offers-preview
rm -rf /opt/car-offers-data

# Confirm disk drop
df -h /
```

### 5.2 Update RUNBOOK.md with new per-project paths

Each project now has "prod server paths" that differ from its old "dev server paths." Update RUNBOOK.md entries.

### 5.3 Consider dev droplet downsize

Dev is now only Claude + orchestration. Could drop from 4 GB to 2 GB ($32 → $16/mo). Or leave at 4 GB for experimentation room. Your call.

### 5.4 Update `/etc/claude-projects.conf`

Project chats' CWDs still point at `/opt/<project>/` which now don't exist. Two options:
- **A:** Project chats stay on dev (CWD stays at `/opt/<project>/` — we re-clone the source there, so chats can `git pull` + inspect code for planning work, but services run on prod).
- **B:** Project chats SSH to prod to execute, work on source checkouts on dev.

**Recommendation: A.** Keep a source-only checkout on dev. Services run on prod but the project chat still has local read access to code.

---

## What this plan does NOT change

- User's bookmarks (`casinv.dev/remote/<project>.html`) — unchanged.
- `casinv.dev` URLs — unchanged (reverse-proxy preserves every path).
- Claude chats — unchanged (they stay on dev).
- Cron / watchdog / telemetry — unchanged (running on dev, monitoring dev's chats).
- The compliance droplet — separate future step, not affected.

## What to watch for during / after

1. **Smoketest at every step.** If it goes from 17/17 → 16/17, stop and diagnose before proceeding.
2. **Capacity on dev should drop as apps leave.** RAM should go below 50% once all 4 apps are on prod.
3. **Capacity on prod rises as apps arrive.** Watch `capacity.json` — if prod needs its own monitor, I'll ship that in Phase 0.6 (TBD).
4. **`projects-smoketest.sh` cron on dev** runs hourly and records to `/var/www/landing/smoketest.json`. Check it anytime.
5. **Rollback is always a nginx revert on dev** — 30 seconds, no data loss.

## Estimated total wall-clock time

- Phase 0 (user actions + my bootstrap): 30-45 min elapsed (~15 min of user clicks, the rest is apt + provisioning).
- Phase 1 (timeshare): 30 min active, plus 2h observation.
- Phase 2 (gym): 20 min active, plus 1h observation.
- Phase 3 (carvana): 2-4 hours active (rsync of 34 GB dominates), plus overnight observation.
- Phase 4 (car-offers): 1 hour active, plus overnight observation.
- Phase 5 (cleanup): 30 min, only after 24-48h at CHECKPOINT 4.

**Realistic timeline: start Phase 0 → 2-3 days to full migration complete.** Most of that is observation intervals, not active work.

---

## Ready-to-go checklist

- [ ] User created new droplet in DO console (16 GB / 4 vCPU Premium Intel).
- [ ] User pasted public + private IP here.
- [ ] User confirmed both SSH keys are on the new droplet.
- [ ] Infra agent confirmed SSH works + bootstrapped base packages.
- [ ] Infra agent confirmed site-deploy clone on prod + private-network shortcut on dev.
- [ ] Baseline smoketest on dev recorded (currently 17/17).
- [ ] Capacity trending captured before migration (currently RAM 70%, disk 74%).

When the first four boxes are checked, say "proceed to Phase 1."
