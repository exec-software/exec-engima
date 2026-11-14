#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/nil.sh check|build|run|test|describe [nilbuild options]

Set NIL_SDK to the NIL SDK directory containing nilbuild and nilcompiler.
Otherwise use .sdk, the sibling exec-nil-framework/sdk, or nilbuild on PATH.
All commands enable NIL_STRICT_BOUNDS=1.
EOF
}

if [[ $# -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

command_name="$1"
shift
case "$command_name" in
    check|build|run|test|describe) ;;
    *) printf 'Unsupported nilbuild command. See ./scripts/nil.sh --help.\n' >&2; exit 2 ;;
esac

source "$script_directory/sdk.sh"
enigma_setup_sdk
exec "$enigma_sdk_directory/nilbuild" "$command_name" \
    --project "$enigma_project_root/nil.project.nildata" \
    --sdk "$enigma_sdk_directory" "$@"
