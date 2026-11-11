#!/bin/bash
# Copy the page to the web root and restart the API server.
#   deploy/deploy.sh /var/www/promptgame [service-name]
set -euo pipefail
cd "$(dirname "$0")/.."
WEBROOT="${1:?usage: deploy/deploy.sh <web root> [service name]}"
SERVICE="${2:-promptgame}"
rsync -a --delete web/ "$WEBROOT"/
sudo systemctl restart "$SERVICE"
sleep 1
systemctl is-active "$SERVICE"
