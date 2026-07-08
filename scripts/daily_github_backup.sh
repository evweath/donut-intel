#!/usr/bin/env bash
#
# daily_github_backup.sh — checks in all session records to GitHub once a day.
#
# Backs up TWO things:
#   1. The donut-intel code repo (commit working tree + push current branch)
#   2. The Claude conversation transcripts (.jsonl) to a SEPARATE PRIVATE repo
#
# Auth: relies on `gh auth login` + `gh auth setup-git` (HTTPS credential
# helper) so pushes run non-interactively. No SSH passphrase needed.
#
# Installed as a launchd job — see com.donutintel.backup.plist.

set -uo pipefail

CODE_REPO="/Users/evw/dev/productComparison/donut-intel"
TRANSCRIPT_SRC="/Users/evw/.claude/projects/-Users-evw-dev-productComparison"
TRANSCRIPT_REPO="/Users/evw/.claude/session-backups/donut-intel"
TRANSCRIPT_REMOTE="https://github.com/evweath/donut-intel-sessions.git"
LOG="$CODE_REPO/logs/daily_github_backup.log"

STAMP="$(date '+%Y-%m-%d %H:%M:%S %Z')"
log() { echo "[$STAMP] $*" >> "$LOG"; }

log "=== backup run start ==="

# ---- 1. Code repo ----------------------------------------------------------
cd "$CODE_REPO" || { log "ERROR: cannot cd to code repo"; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "Claude session backup: $STAMP" \
    && log "code: committed working tree" \
    || log "code: commit failed"
else
  log "code: nothing to commit"
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if git push -q origin "HEAD:$BRANCH"; then
  log "code: pushed $BRANCH"
else
  log "code: PUSH FAILED (check gh auth / remote)"
fi

# ---- 2. Transcripts (private repo) -----------------------------------------
mkdir -p "$TRANSCRIPT_REPO"
cd "$TRANSCRIPT_REPO" || { log "ERROR: cannot cd to transcript repo"; exit 1; }
if [ ! -d .git ]; then
  git init -q
  git remote add origin "$TRANSCRIPT_REMOTE" 2>/dev/null || true
  log "transcripts: initialized local repo"
fi
# Mirror all transcript files for THIS project into the backup repo.
rsync -a --delete-excluded --include='*.jsonl' --include='*/' --exclude='*' \
  "$TRANSCRIPT_SRC/" "$TRANSCRIPT_REPO/data/" 2>>"$LOG"
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "Session transcripts backup: $STAMP" \
    && log "transcripts: committed" \
    || log "transcripts: commit failed"
else
  log "transcripts: no changes"
fi
if git push -q origin HEAD 2>>"$LOG"; then
  log "transcripts: pushed"
else
  log "transcripts: PUSH FAILED (repo may not exist yet / auth)"
fi

log "=== backup run end ==="
