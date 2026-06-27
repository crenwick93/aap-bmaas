#!/usr/bin/env bash
set -euo pipefail
# dnf install -y lorax   (provides mkksiso)
INPUT_ISO="${1:-rhel-9-x86_64-dvd.iso}"
OUTPUT_ISO="/srv/iso/rhel9-unattended.iso"
mkksiso --ks kickstart/ks.cfg "${INPUT_ISO}" "${OUTPUT_ISO}"
echo "Built: ${OUTPUT_ISO}"
