#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")" && pwd)"
CERT_FILE="$CERT_DIR/local-dev.pem"
KEY_FILE="$CERT_DIR/local-dev-key.pem"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
  echo "Certs already exist at $CERT_DIR. Delete them to regenerate."
  exit 0
fi

if ! command -v mkcert &>/dev/null; then
  echo "mkcert is not installed."
  echo "Install it:"
  echo "  Ubuntu/Debian: sudo apt install mkcert"
  echo "  macOS:         brew install mkcert"
  echo "  Other:         https://github.com/FiloSottile/mkcert#installation"
  exit 1
fi

mkcert -install
mkcert -cert-file "$CERT_FILE" -key-file "$KEY_FILE" \
  app.localhost api.localhost localhost 127.0.0.1 ::1

echo "Certs generated:"
echo "  $CERT_FILE"
echo "  $KEY_FILE"
