#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SOURCE="$SCRIPT_DIR/dist/Beamer.app"
DEST_APP="/Applications/Beamer.app"
DEST_TUNNEL="/Applications/Beamer Tunnel.command"

trap 'status=$?; echo "Installation failed."; read -r -p "Press Return to close"; exit $status' ERR

"$SCRIPT_DIR/build_dmg.sh"
killall Beamer 2>/dev/null || true

# The app was called OpenKB until 19-08-2026. Two copies in /Applications is
# how Spotlight ends up offering both, so the old one goes. Its data directory
# is deliberately left alone -- it still holds the config and auth token.
killall OpenKB 2>/dev/null || true
rm -rf "/Applications/OpenKB.app" "/Applications/OpenKB Tunnel.command"

# The app was called Beamy until 10-09-2026. Same reasoning as the OpenKB
# cleanup above: two copies in /Applications is how Spotlight ends up
# offering both, so the old one goes.
killall Beamy 2>/dev/null || true
rm -rf "/Applications/Beamy.app" "/Applications/Beamy Tunnel.command"
# Beamy shared the OpenKB bundle id (never got its own); Beamer uses a new
# one, so uk.co.kalkman.openkb.desktop's grants now belong to an app that no
# longer exists.
tccutil reset Accessibility uk.co.kalkman.openkb.desktop >/dev/null 2>&1 || true
tccutil reset ListenEvent uk.co.kalkman.openkb.desktop >/dev/null 2>&1 || true

rm -rf "$DEST_APP"
ditto "$APP_SOURCE" "$DEST_APP"
ditto "$SCRIPT_DIR/Beamer Tunnel.command" "$DEST_TUNNEL"
chmod +x "$DEST_TUNNEL"
xattr -cr "$DEST_APP"

# An ad-hoc build is a different code identity on every build wearing the same bundle id. macOS
# keeps the old grant against the old identity, which is why such a reinstall can sit in the
# Privacy pane with a tick beside it and still receive no events -- the tick belongs to a build
# that no longer exists. Revoking turns that silent failure into a visible prompt.
# Only ad-hoc builds need it. Since 31-08-2026 build_dmg.sh signs with a real identity where one
# is reachable, and that identity is stable across rebuilds, so the grants carry over and
# revoking them would throw away the very thing the signing bought. The ad-hoc path still
# exists for builds driven over SSH, where the login keychain cannot be unlocked.
# Resetting resolves the id through LaunchServices, so it runs after the new bundle is in place,
# and never blocks the install: a first install on a clean machine has nothing to revoke.
BUNDLE_ID="uk.co.kalkman.beamer"
if codesign -dv "$DEST_APP" 2>&1 | grep -q "Signature=adhoc"; then
    for service in Accessibility ListenEvent LocalNetwork; do
        if tccutil reset "$service" "$BUNDLE_ID" >/dev/null 2>&1; then
            echo "Revoked $service"
        else
            echo "Nothing to revoke for $service"
        fi
    done
    REVOKED=1
else
    REVOKED=0
fi

# The app is installed, so the staged copy has done its job and must not survive. Spotlight
# indexes any .app left under build/ or dist/, which puts a second Beamer in Launchpad beside the
# real one with no way to tell them apart. build_dmg.sh stages inside the repo, so nothing else
# clears these.
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"

echo "Beamer is installed at $DEST_APP"
echo "The macOS 27 fallback is installed at $DEST_TUNNEL"
if [ "$REVOKED" -eq 1 ]; then
    echo "This build is ad-hoc signed, so its privacy permissions were revoked on install. Grant Accessibility and Input Monitoring again, one at a time, inside the app."
else
    echo "Signed with a stable identity, so Accessibility and Input Monitoring carry over. Grant them inside the app only if it asks."
fi
read -r -p "Press Return to close" || true
