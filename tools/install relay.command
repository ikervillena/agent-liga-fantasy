#!/bin/bash
# Install the relay: keeps this folder and GitHub in sync every five minutes.
# so changes made here reach the agent and its state lands back here.
# Double-click from Finder. One time only.
set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.ikervillena.fantasy-agent.relay"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT="$REPO_DIR/tools/relay.sh"
clear

echo "Repository: $REPO_DIR"
echo

[ -d "$REPO_DIR/.git" ] || {
  echo "Not a git repository yet. Run 'publish to github.command' first."
  echo; read -r -p "Press Enter to close."; exit 1
}

cat > "$SCRIPT" <<'RELAY'
#!/bin/bash
# Pull whatever the agent committed, push whatever changed here.
cd "$(dirname "$0")/.." || exit 0
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

# Bring down whatever the agent committed from CI.
git pull --rebase --autostash --quiet || exit 0

# Push up whatever changed here. This is the whole reason the relay exists:
# it runs as you, with your keychain, so nothing else needs a credential.
git add -A 2>/dev/null
git diff --cached --quiet || {
  git commit -q -m "local: $(date -u '+%Y-%m-%d %H:%M UTC')"
  git push --quiet || true
}
RELAY
chmod +x "$SCRIPT"

mkdir -p "$HOME/Library/LaunchAgents" "$REPO_DIR/state"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$SCRIPT</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/$LABEL.log</string>
  <key>StandardErrorPath</key><string>/tmp/$LABEL.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null
if launchctl load "$PLIST" 2>/dev/null; then
  echo "Relay installed. Syncs every five minutes while this Mac is awake."
  echo "To stop it:  launchctl unload $PLIST"
else
  echo "Could not load it. Try by hand:  launchctl load $PLIST"
fi

echo
read -r -p "Press Enter to close."
