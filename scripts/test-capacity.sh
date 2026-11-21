#!/usr/bin/env bash
# Run the same expanded-store and byte-refusal contract through both hosts.
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_directory/sdk.sh"
enigma_setup_sdk
target="all"
if [[ $# -eq 2 && "$1" == "--target" ]]; then
    target="$2"
elif [[ $# -ne 0 ]]; then
    printf 'Usage: ./scripts/test-capacity.sh [--target vm|native|all]\n' >&2
    exit 2
fi
case "$target" in
    all) routes=(vm native) ;;
    vm|native) routes=("$target") ;;
    *) printf 'Target must be vm, native, or all.\n' >&2; exit 2 ;;
esac

for project in "$enigma_project_root/host/nil.project.nildata" \
               "$enigma_project_root/validation/capacity/nil.project.nildata"; do
    "$enigma_sdk_directory/nilbuild" check --project "$project" --sdk "$enigma_sdk_directory"
    "$enigma_sdk_directory/nilbuild" build --project "$project" --sdk "$enigma_sdk_directory" --target "$target"
done
"$script_directory/build-storage.sh" --target "$target"

run_suite() {
    local route="$1" typed="$2"
    shift 2
    ENIGMA_CAPACITY_TESTS=1 ENIGMA_CAPACITY_TYPED="$typed" ENIGMA_TEST_TARGETS="$route" \
        PYTHONDONTWRITEBYTECODE=1 NIL_SDK="$enigma_sdk_directory" ENIGMA_HOST_COMMAND="$*" \
        python3 -I -m unittest discover -s "$enigma_project_root/tests" -p test_capacity.py -v -f
}

for route in "${routes[@]}"; do
    if [[ "$route" == "vm" ]]; then
        run_suite "$route" 1 "$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/build/host/enigma-durable-host.nil"
    else
        run_suite "$route" 1 "$enigma_project_root/build/host/enigma-durable-host"
    fi
    run_suite "$route" 0 "$(command -v python3)" "$enigma_project_root/scripts/store.py"
done
