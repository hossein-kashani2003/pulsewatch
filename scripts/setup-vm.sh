#!/usr/bin/env bash
# install Docker + firewall on Debian 12/13. Run with: sudo bash scripts/setup-vm.sh
set -euo pipefail
TARGET_USER="${SUDO_USER:-$USER}"

apt-get update
apt-get install -y ca-certificates curl gnupg ufw git make openssl

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$TARGET_USER"

# firewall: allow only SSH and web traffic
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "done. logout/login so the docker group applies to $TARGET_USER"
