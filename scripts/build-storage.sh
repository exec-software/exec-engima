#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_directory/sdk.sh"
enigma_setup_sdk
exec "$enigma_sdk_directory/nilbuild" build \
    --project "$enigma_project_root/storage/nil.project.nildata" \
    --sdk "$enigma_sdk_directory" "$@"
