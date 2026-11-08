#!/usr/bin/env bash
# Install a dedicated key-only reverse-forward account; does not change SSH port.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo' >&2; exit 1; fi
if [[ $# -ne 1 || ! -f $1 ]]; then echo 'Usage: sudo bash Setup-Raspi.sh /path/to/backup-ai.pub' >&2; exit 1; fi
command -v sshd >/dev/null || { echo 'Install openssh-server first' >&2; exit 1; }
ssh-keygen -lf "$1" >/dev/null
key=$(awk 'NF {print $1 " " $2}' "$1")
[[ $key == ssh-ed25519\ * && $(printf '%s\n' "$key" | wc -l) -eq 1 ]] || { echo 'Expected one Ed25519 public key' >&2; exit 1; }
account=serversstatus-ai-tunnel
account_dir=/var/lib/serversstatus-ai-tunnel
config=/etc/ssh/sshd_config.d/90-serversstatus-ai-tunnel.conf
if ! id "$account" >/dev/null 2>&1; then
    useradd --system --home-dir "$account_dir" --shell /usr/sbin/nologin "$account"
else
    [[ $(getent passwd "$account" | cut -d: -f6) == "$account_dir" && $(getent passwd "$account" | cut -d: -f7) == /usr/sbin/nologin ]] || { echo 'Existing account has unexpected home/shell; nothing changed' >&2; exit 1; }
fi
# Public-key auth on Raspberry Pi OS uses PAM; random unusable password hash avoids
# locked-account rejection on sshd installations with UsePAM=no. Password login is disabled below.
if [[ $(passwd -S "$account" | awk '{print $2}') == L ]]; then
    random_hash=$(openssl rand -hex 32 | openssl passwd -6 -stdin)
    usermod --password "$random_hash" "$account"
fi
install -d -m 0755 -o root -g root "$account_dir"
install -d -m 0755 -o root -g root "$account_dir/.ssh"
authorized_tmp=$(mktemp)
config_tmp=$(mktemp)
trap 'rm -f "$authorized_tmp" "$config_tmp"' EXIT
printf 'restrict,port-forwarding,permitlisten="127.0.0.1:18091" %s\n' "$key" > "$authorized_tmp"
cat > "$config_tmp" <<'EOF'
# Managed by ServersStatus AI reverse tunnel. Only this account is affected.
Match User serversstatus-ai-tunnel
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    AuthorizedKeysFile /var/lib/serversstatus-ai-tunnel/.ssh/authorized_keys
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding remote
    PermitListen 127.0.0.1:18091
    GatewayPorts no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    PermitTunnel no
    MaxSessions 0
Match all
EOF
install -d -m 0755 /etc/ssh/sshd_config.d
# sshd must actually include this directory; do not append a second global block blindly.
if ! /usr/sbin/sshd -T | grep -q '^pubkeyauthentication yes'; then echo 'Review existing SSH key authentication policy first' >&2; exit 1; fi
backup=$(mktemp)
existed=false
if [[ -f $config ]]; then cp "$config" "$backup"; existed=true; fi
install -m 0644 -o root -g root "$config_tmp" "$config"
if ! /usr/sbin/sshd -t; then
    if $existed; then install -m 0644 "$backup" "$config"; else rm -f "$config"; fi
    rm -f "$backup"
    echo 'SSH config rejected; previous drop-in restored' >&2; exit 1
fi
# Check effective restrictions, including that sshd_config includes the new file.
effective=$(/usr/sbin/sshd -T -C "user=$account,host=localhost,addr=127.0.0.1")
for required in 'allowtcpforwarding remote' 'permitlisten 127.0.0.1:18091' 'maxsessions 0' 'passwordauthentication no' 'gatewayports no'; do
    if ! printf '%s\n' "$effective" | grep -Fqx "$required"; then
        if $existed; then install -m 0644 "$backup" "$config"; else rm -f "$config"; fi
        rm -f "$backup"
        echo "Effective SSH restriction missing: $required. Previous config restored." >&2; exit 1
    fi
done
rm -f "$backup"
install -m 0644 -o root -g root "$authorized_tmp" "$account_dir/.ssh/authorized_keys"
systemctl reload ssh
printf '\nUse this public HOST KEY on Backup (it is not a password/private key):\n'
awk '{print $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
printf '\nAccount ready. Router TCP 2222 should forward to Raspberry Pi TCP 22.\n'
