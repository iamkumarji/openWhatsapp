#!/usr/bin/env bash
# One-shot Ubuntu server prep for WAINT. Run as root on a fresh 22.04/24.04 host.
set -euo pipefail

echo "==> packages"
apt-get update && apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg ufw fail2ban age awscli

echo "==> docker"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> firewall (only 80/443 + SSH)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> fail2ban"
systemctl enable --now fail2ban

echo "==> swap + sysctls (helps Ollama + Postgres)"
if [ ! -f /swapfile ]; then
  fallocate -l 8G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
echo "vm.overcommit_memory=1" >> /etc/sysctl.d/99-waint.conf
sysctl --system

echo "==> done. Next: clone repo, cp .env.example .env, edit, then follow docs/05."
