#!/bin/sh
# Deploy local crm to the CRM appliance at 192.168.1.9.
#
# Pushes to the `deploy` remote (bare repo /home/admin/crm-origin.git on the
# server), updates the deploy dir /opt/crm to it, rebuilds and restarts the crm
# container, re-runs the one-shot migrations service, then probes the live
# /health/ready endpoint in-container with bounded retry.
#
# The crm appliance is launched as part of the crm_mira Compose project:
# compose.crm.yaml (in /opt/crm_mira) includes ../crm/compose.yaml, so Compose
# is driven from /opt/crm_mira with both files while git ops target /opt/crm.
# The migrations one-shot is force-recreated so migration-only changes (no crm
# image change) still apply: Compose does not recreate a completed one-shot
# from bind-mount content alone.
#
# Refuses to run with uncommitted LOCAL changes (tracked files).
# On the server, any unexpected uncommitted changes in the deploy dir are
# stashed (git stash --include-untracked) with a WARNING before the dir is
# reset to origin. Nothing is silently discarded.
#
# Usage: ./scripts/deploy_remote.sh
set -eu

cd "$(dirname "$0")/.."
SERVER=admin@192.168.1.9
GIT_DIR=/opt/crm
COMPOSE_DIR=/opt/crm_mira
COMPOSE="docker compose -f compose.yaml -f compose.crm.yaml"
BRANCH=main

if [ -n "$(git diff --name-only)" ]; then
    echo "refusing to deploy: uncommitted changes to tracked files" >&2
    git diff --stat >&2
    exit 1
fi

git push deploy "$BRANCH"

# $GIT_DIR, $COMPOSE_DIR and $COMPOSE are expanded locally (the remote shell does not have them);
# every other \$-prefixed token is expanded by the remote shell.
ssh "$SERVER" "set -e
cd $GIT_DIR
git fetch origin
# Stash any unexpected local changes before resetting to origin.
if [ -n \"\$(git diff --name-only HEAD)\" ] || [ -n \"\$(git ls-files --others --exclude-standard)\" ]; then
    git stash push --include-untracked -m \"saved before deploy \$(date -u +%Y%m%dT%H%M%SZ)\"
    echo \"WARNING: unexpected uncommitted changes in $GIT_DIR stashed before reset. Recover with: cd $GIT_DIR && git stash list && git stash apply\" >&2
fi
git reset --hard origin/$BRANCH
cd $COMPOSE_DIR
$COMPOSE build crm
$COMPOSE up -d --force-recreate migrations crm
echo 'Waiting 15 seconds for app startup...'
sleep 15
attempts=0
until $COMPOSE exec -T crm python -c 'import sys,urllib.request; r=urllib.request.urlopen(\"http://127.0.0.1:8000/health/ready\",timeout=5); sys.exit(0 if r.status==200 else 1)'; do
    attempts=\$((attempts + 1))
    if [ \$attempts -ge 15 ]; then
        echo 'post-server /health/ready probe failing after 15 attempts' >&2
        exit 1
    fi
    sleep 2
done
"
echo "deploy complete"
