#!/usr/bin/env bash
# Optional account key: never echo it or pass it in process arguments.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo bash Enable-AISearch.sh' >&2; exit 1; }
id serversstatus >/dev/null
[[ -d /var/lib/serversstatus ]] || install -d -m 0700 -o serversstatus -g serversstatus /var/lib/serversstatus
read -r -s -p 'Paste Tavily API key (hidden; Enter cancels): ' search_secret
printf '\n'
[[ -n $search_secret ]] || { unset search_secret; echo 'Cancelled; existing key preserved.'; exit 0; }
[[ ${#search_secret} -ge 16 && ${#search_secret} -le 256 && $search_secret =~ ^[A-Za-z0-9_-]+$ ]] || { unset search_secret; echo 'Invalid key format; existing key preserved.' >&2; exit 1; }
temp=$(mktemp /var/lib/serversstatus/.ai-search-key.XXXXXX)
trap 'rm -f "$temp"; unset search_secret' EXIT
chmod 0600 "$temp"
printf '%s' "$search_secret" > "$temp"
unset search_secret
chown serversstatus:serversstatus "$temp"
mv -f "$temp" /var/lib/serversstatus/ai-search-key
systemctl restart serversstatus
echo 'Key saved (0600, owner serversstatus); web service restarted.'
echo 'API validity is checked on the next search. Do not send the key in chat or logs.'
