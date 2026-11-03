#!/usr/bin/env bash
# create a self-signed certificate for testing. In production use Let's Encrypt.
set -euo pipefail
DIR="${1:-./nginx/certs}"
mkdir -p "$DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout "$DIR/server.key" -out "$DIR/server.crt" \
  -subj "/CN=pulsewatch.local" \
  -addext "subjectAltName=DNS:pulsewatch.local,DNS:localhost,IP:127.0.0.1,IP:192.168.56.10"
chmod 600 "$DIR/server.key"
echo "certs written to $DIR"
