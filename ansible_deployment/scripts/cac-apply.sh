#!/usr/bin/env bash
set -euo pipefail

# Apply AAP Controller objects for bare-metal RHEL 9 provisioning.
# Sources the repo-root .env for AAP and iDRAC credentials.
#
# Usage:
#   ./ansible_deployment/scripts/cac-apply.sh
#
# Prerequisites:
#   ansible-galaxy collection install -r ansible_deployment/cac/requirements.yml
#
# Required env (from top-level .env):
#   AAP_HOSTNAME          — AAP gateway URL (e.g. https://aaponprem.chrislab.dev)
#   AAP_TOKEN             — AAP OAuth2 token
#   IDRAC_PASSWORD        — iDRAC root password
#
# Optional:
#   AAP_VALIDATE_CERTS    — true|false (default: false for self-signed)
#   GIT_REPO_URL          — override project repo (default: aap-bmaas on GitHub)
#   CUSTOM_EE_IMAGE       — custom EE image with omsdk + dellemc.openmanage
#   T620_SSH_KEY_PATH     — path to SSH private key for post-provision access

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PLAYBOOK="${REPO_ROOT}/ansible_deployment/cac/apply.yml"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  echo "Loading environment from ${REPO_ROOT}/.env"
  # shellcheck disable=SC2046
  export $(grep -v '^#' "${REPO_ROOT}/.env" | xargs -I{} echo {})
fi

ansible-playbook "${PLAYBOOK}" "$@"
