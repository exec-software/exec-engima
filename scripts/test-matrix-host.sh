#!/usr/bin/env bash
# ENI-0003 phase C: run the black-box session contract against the Matrix host.
#
# The Matrix host needs NIL-0028 through NIL-0030, which no installed SDK has,
# so this is separate from ./scripts/test.sh and fails clearly when the
# declarations or providers are absent. The same suite also runs against
# scripts/store.py, which remains the qualified persistence path.
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_directory/sdk.sh"
enigma_setup_sdk

target="all"
if [[ $# -eq 2 && "$1" == "--target" ]]; then
    target="$2"
elif [[ $# -ne 0 ]]; then
    printf 'Usage: ./scripts/test-matrix-host.sh [--target vm|native|all]\n' >&2
    exit 2
fi
case "$target" in
    all) routes=(vm native) ;;
    vm|native) routes=("$target") ;;
    *) printf 'Target must be vm, native, or all.\n' >&2; exit 2 ;;
esac

"$enigma_sdk_directory/nilbuild" check \
    --project "$enigma_project_root/host/nil.project.nildata" --sdk "$enigma_sdk_directory"
"$enigma_sdk_directory/nilbuild" build \
    --project "$enigma_project_root/host/nil.project.nildata" --sdk "$enigma_sdk_directory" \
    --target "$target"
# Candidate validation and payload identity are Matrix logic now, so they are
# tested in Matrix beside the implementation rather than from a Python seam.
"$enigma_sdk_directory/nilbuild" test \
    --project "$enigma_project_root/host/nil.project.nildata" --sdk "$enigma_sdk_directory" \
    --target "$target" --filter enigma.host > /dev/null
printf 'PASS matrix host logic %s\n' "$target"

# The worker is still built, because the Python host spawns it and the
# comparison run below has to exercise the path that is still qualified.
"$script_directory/build-storage.sh" --target "$target"

run_suite() {
    local label="$1"
    shift
    ENIGMA_TEST_TARGETS=vm NIL_SDK="$enigma_sdk_directory" ENIGMA_HOST_COMMAND="$*" \
        python3 -I -m unittest discover -s "$enigma_project_root/tests" \
        -p 'test_storage_recovery.py' > /dev/null
    printf 'PASS session contract %s\n' "$label"
    # Faults injected from the filesystem and the process environment, so the
    # host under test needs no seam of its own. Both hosts must satisfy these:
    # a scenario only one of them passes describes that host, not the contract.
    ENIGMA_TEST_TARGETS=vm NIL_SDK="$enigma_sdk_directory" ENIGMA_HOST_COMMAND="$*" \
        python3 -I -m unittest discover -s "$enigma_project_root/tests" \
        -p 'test_host_faults.py' > /dev/null
    printf 'PASS storage faults %s\n' "$label"
}

for route in "${routes[@]}"; do
    if [[ "$route" == "vm" ]]; then
        run_suite "matrix-host $route" \
            "$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/build/host/enigma-durable-host.nil"
    else
        run_suite "matrix-host $route" "$enigma_project_root/build/host/enigma-durable-host"
    fi
done

# The Python host must still satisfy the same contract: a half-ported tree has
# two hosts, and neither may regress while the other is being qualified.
run_suite "python-host" "$(command -v python3)" "$enigma_project_root/scripts/store.py"

# Either host must read a database the other created, which is what
# byte-identical checkpoint envelopes buy. A cutover with no cross-check is the
# outcome ENI-0003 exists to avoid.
workspace="$(mktemp -d "${TMPDIR:-/tmp}/enigma-host-interop.XXXXXXXX")"
trap 'rm -rf -- "$workspace"' EXIT
matrix_host=("$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/build/host/enigma-durable-host.nil")
python_host=(python3 "$enigma_project_root/scripts/store.py")

check_interop() {
    local label="$1" directory="$2"
    shift 2
    local ready
    ready="$(printf '' | NIL_SDK="$enigma_sdk_directory" "$@" serve "$directory")"
    if [[ "$ready" != *'"code":"ready"'* ]]; then
        printf 'FAIL interop %s: %s\n' "$label" "$ready" >&2
        exit 1
    fi
    printf 'PASS interop %s\n' "$label"
}

NIL_SDK="$enigma_sdk_directory" "${matrix_host[@]}" init "$workspace/from-matrix" --scope work > /dev/null
check_interop "python host reads a matrix database" "$workspace/from-matrix" "${python_host[@]}"
NIL_SDK="$enigma_sdk_directory" "${python_host[@]}" init "$workspace/from-python" --scope work > /dev/null
check_interop "matrix host reads a python database" "$workspace/from-python" "${matrix_host[@]}"
