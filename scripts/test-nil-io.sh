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
    python3 -I - "$temporary/$route" "$enigma_project_root" <<'PY'
import fcntl, hashlib, importlib.util, json, os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
# The real Python host, so the comparison is against its encoder rather than a
# restatement of it here.
spec = importlib.util.spec_from_file_location(
    "enigma_store_host", Path(sys.argv[2]) / "scripts" / "store.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
assert {p.name for p in root.iterdir()} == {
    'snapshot.json', 'writer.lock', 'payload.sha256', 'checkpoint.envelope', 'store'}
payload = (root / 'snapshot.json').read_bytes()
state = json.loads(payload)
assert state['grants'][0]['revoked'] is True
assert state['clock_floor'] == 1
for name in ('snapshot.json', 'writer.lock', 'payload.sha256', 'checkpoint.envelope'):
    assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
# The engine created this directory itself through the public surface.
store = root / 'store'
info = store.lstat()
assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
assert stat.S_IMODE(info.st_mode) == 0o700
assert {p.name for p in store.iterdir()} == {'snapshot.json'}
published = store / 'snapshot.json'
assert stat.S_IMODE(published.stat().st_mode) == 0o600
assert published.read_bytes() == payload
# Recompute the digest the way the Python host does, so a Matrix checkpoint
# envelope and a store.py envelope cannot silently disagree. ENI-0003 makes
# byte-identical envelopes the precondition for porting the host.
assert (root / 'payload.sha256').read_bytes().decode('ascii') == \
    hashlib.sha256(payload).hexdigest()
# ENI-0003 phase B: the envelope Matrix built over real Enigma state must be
# the exact bytes this host would write for the same payload, so either host
# can read a directory the other wrote.
expected = host._json_bytes({
    'format': host.FORMAT, 'payload': payload.decode('utf-8'),
    'sha256': hashlib.sha256(payload).hexdigest()})
observed = (root / 'checkpoint.envelope').read_bytes()
assert observed == expected, (
    'Matrix and store.py envelopes diverge: %r != %r' % (observed[:120], expected[:120]))
# And this host accepts what Matrix wrote, not merely bytes that look alike.
assert host.strict_json(observed)['payload'] == payload.decode('utf-8')
fd = os.open(root / 'writer.lock', os.O_RDWR | os.O_NOFOLLOW)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
finally:
    os.close(fd)
PY
    printf 'PASS NIL I/O consumer %s\n' "$route"
done
