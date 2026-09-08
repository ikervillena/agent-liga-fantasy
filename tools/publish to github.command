#!/bin/bash
# One-time: push this repository to GitHub. Double-click from Finder.
set -u
cd "$(dirname "$0")/.." || exit 1
clear

echo "=================================================="
echo "  Publish fantasy-agent to GitHub"
echo "=================================================="
echo

command -v git >/dev/null 2>&1 || {
  echo "git is missing. Install the Command Line Tools:  xcode-select --install"
  echo; read -r -p "Press Enter to close."; exit 1
}

read -r -p "Repository URL: " REPO
[ -z "$REPO" ] && { echo "Nothing to do without a URL."; read -r -p "Enter to close."; exit 1; }

[ -d .git ] || { git init -q; git branch -M main; }
git remote remove origin 2>/dev/null
git remote add origin "$REPO"

git add -A
git diff --cached --quiet || git commit -q -m "fantasy-agent: autonomous LaLiga Fantasy manager"

echo
echo "Pushing. If it asks for a password, use a GitHub personal access token."
if git push -u origin main; then
  cat <<'DONE'

Done. Two things left, both in the repository settings on github.com:

  1. Settings -> Secrets and variables -> ACTIONS -> New repository secret
       FANTASY_EMAIL      your LaLiga Fantasy email
       FANTASY_PASSWORD   your LaLiga Fantasy password
       TELEGRAM_TOKEN     from BotFather
       TELEGRAM_CHAT_ID   your Telegram user id

  2. The Actions tab -> enable workflows.

Then: Actions -> agent -> Run workflow, with "Send the daily brief" ticked.
DONE
else
  echo
  echo "Push failed. Usually the URL is wrong or the repo does not exist yet."
fi

echo
read -r -p "Press Enter to close."
