#!/usr/bin/env bash
# Store the model key locally without echoing it or placing it in command history.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo bash Enable-PortalAI.sh' >&2; exit 1; }
id serversstatus >/dev/null
curl --noproxy '*' --fail --silent --show-error --max-time 15 http://127.0.0.1:18091/health >/dev/null
[[ -d /var/lib/serversstatus ]] || install -d -m 0700 -o serversstatus -g serversstatus /var/lib/serversstatus
read -r -s -p 'Paste API key from Backup api-key.txt (hidden): ' ai_secret
printf '\n'
[[ ${#ai_secret} -ge 16 && ${#ai_secret} -le 256 && $ai_secret =~ ^[A-Za-z0-9+/=_-]+$ ]] || { unset ai_secret; echo 'Invalid key format' >&2; exit 1; }
# Validate the key through the tunnel without putting it into curl argv/history.
printf 'header = "Authorization: Bearer %s"\n' "$ai_secret" | curl --noproxy '*' --config - --fail --silent --show-error --max-time 15 http://127.0.0.1:18091/v1/models >/dev/null
temp=$(mktemp /var/lib/serversstatus/.ai-key.XXXXXX)
trap 'rm -f "$temp"; unset ai_secret' EXIT
chmod 0600 "$temp"
printf '%s' "$ai_secret" > "$temp"
unset ai_secret
chown serversstatus:serversstatus "$temp"
mv -f "$temp" /var/lib/serversstatus/ai-api-key
systemctl restart serversstatus
echo 'AI key stored locally. Open /ai in the portal with an administrative account.'
