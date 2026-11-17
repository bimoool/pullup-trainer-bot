#!/usr/bin/env bash
set -euo pipefail
exec env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  HOME=/root LANG=C.UTF-8 SSH_ORIGINAL_COMMAND="${SSH_ORIGINAL_COMMAND:-}" \
  python3 /root/bin/control-plane-supervisor.py
