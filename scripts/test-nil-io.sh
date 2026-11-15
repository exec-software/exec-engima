#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_directory/sdk.sh"
enigma_setup_sdk
target="all"
if [[ $# -eq 2 && "$1" == "--target" ]]; then
    target="$2"
elif [[ $# -ne 0 ]]; then
    printf 'Usage: ./scripts/test-nil-io.sh [--target vm|native|all]\n' >&2
    exit 2
fi
case "$target" in
    all) routes=(vm native) ;;
    vm|native) routes=("$target") ;;
    *) printf 'Target must be vm, native, or all.\n' >&2; exit 2 ;;
esac
"$enigma_sdk_directory/nilbuild" check --project "$enigma_project_root/validation/nil-io/nil.project.nildata" --sdk "$enigma_sdk_directory"
"$enigma_sdk_directory/nilbuild" build --project "$enigma_project_root/validation/nil-io/nil.project.nildata" --sdk "$enigma_sdk_directory" --target "$target"
temporary="$(mktemp -d "${TMPDIR:-/tmp}/enigma-nil-io.XXXXXXXX")"
trap 'rm -rf -- "$temporary"' EXIT
for route in "${routes[@]}"; do
    mkdir -m 700 "$temporary/$route"
    if [[ "$route" == "vm" ]]; then
        command=("$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/build/nil-io-contract/enigma-nil-io-contract.nil")
    else
        command=("$enigma_project_root/build/nil-io-contract/enigma-nil-io-contract")
    fi
    "${command[@]}" "$temporary/$route" > "$temporary/stdout"
    [[ "$(< "$temporary/stdout")" == "nil-io-checkpoint-ok" ]]
    python3 - "$temporary/$route" <<'PY'
import fcntl, json, os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
assert {p.name for p in root.iterdir()} == {'snapshot.json', 'writer.lock'}
state = json.loads((root / 'snapshot.json').read_bytes())
assert state['grants'][0]['revoked'] is True
assert state['clock_floor'] == 1
for name in ('snapshot.json', 'writer.lock'):
    assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
fd = os.open(root / 'writer.lock', os.O_RDWR | os.O_NOFOLLOW)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
finally:
    os.close(fd)
PY
    printf 'PASS NIL I/O consumer %s\n' "$route"
done
