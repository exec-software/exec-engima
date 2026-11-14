#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_directory/sdk.sh"
enigma_setup_sdk

target="all"
if [[ $# -eq 2 && "$1" == "--target" ]]; then
    target="$2"
elif [[ $# -ne 0 ]]; then
    printf 'Usage: ./scripts/test.sh [--target vm|native|all]\n' >&2
    exit 2
fi
case "$target" in
    vm|native|all) ;;
    *) printf 'Target must be vm, native, or all.\n' >&2; exit 2 ;;
esac

"$script_directory/nil.sh" check
"$enigma_sdk_directory/nilbuild" check \
    --project "$enigma_project_root/ext/enigma-client/nil.project.nildata" --sdk "$enigma_sdk_directory"
"$enigma_sdk_directory/nilbuild" check \
    --project "$enigma_project_root/storage/nil.project.nildata" --sdk "$enigma_sdk_directory"
"$script_directory/nil.sh" test --target "$target"
"$enigma_sdk_directory/nilbuild" test \
    --project "$enigma_project_root/storage/nil.project.nildata" --sdk "$enigma_sdk_directory" \
    --target "$target" --filter enigma.storage
"$script_directory/nil.sh" build --target "$target"
"$enigma_sdk_directory/nilbuild" build \
    --project "$enigma_project_root/ext/enigma-client/nil.project.nildata" --sdk "$enigma_sdk_directory" --target "$target"
"$script_directory/build-storage.sh" --target "$target"

test_directory="$(mktemp -d "${TMPDIR:-/tmp}/enigma-cli.XXXXXXXX")"
trap 'rm -rf -- "$test_directory"' EXIT
IFS= read -r release_version < "$enigma_project_root/VERSION"
printf 'Enigma %s\n' "$release_version" > "$test_directory/version"
printf 'Enigma: unsupported arguments. Use --help.\n' > "$test_directory/error"

case "$target" in
    all) routes=(vm native) ;;
    *) routes=("$target") ;;
esac

fail_case() {
    printf 'FAIL CLI %s: %s\n' "$route" "$1" >&2
    exit 1
}

check_case() {
    local label="$1" expected_status="$2" output_kind="$3" actual_status
    shift 3
    if "${route_command[@]}" "$@" > "$test_directory/stdout" 2> "$test_directory/stderr"; then
        actual_status=0
    else
        actual_status=$?
    fi
    [[ "$actual_status" -eq "$expected_status" ]] || fail_case "$label exit status"
    case "$output_kind" in
        help)
            [[ ! -s "$test_directory/stderr" ]] || fail_case "$label stderr"
            [[ "$(< "$test_directory/stdout")" == *"Usage: enigma "* ]] || fail_case "$label usage"
            [[ "$(< "$test_directory/stdout")" == *"No native isolation."* ]] || fail_case "$label trust boundary"
            if [[ -e "$test_directory/help" ]]; then
                cmp -s "$test_directory/stdout" "$test_directory/help" || fail_case "$label output"
            else
                cp -- "$test_directory/stdout" "$test_directory/help"
            fi
            ;;
        version)
            [[ ! -s "$test_directory/stderr" ]] || fail_case "$label stderr"
            cmp -s "$test_directory/stdout" "$test_directory/version" || fail_case "$label VERSION mismatch"
            ;;
        error)
            [[ ! -s "$test_directory/stdout" ]] || fail_case "$label stdout"
            cmp -s "$test_directory/stderr" "$test_directory/error" || fail_case "$label diagnostic or input disclosure"
            ;;
        demo|surface|client-example)
            [[ ! -s "$test_directory/stderr" ]] || fail_case "$label stderr"
            local fixture_suffix="txt"
            if [[ "$output_kind" == "surface" ]]; then
                fixture_suffix="nildata"
            fi
            cmp -s "$test_directory/stdout" "$enigma_project_root/tests/fixtures/$output_kind.$fixture_suffix" || fail_case "$label contract"
            ;;
    esac
}

for route in "${routes[@]}"; do
    if [[ "$route" == "vm" ]]; then
        route_command=("$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/build/enigma.nil")
    else
        route_command=("$enigma_project_root/build/enigma")
    fi
    check_case default 0 help
    check_case help 0 help --help
    check_case short-help 0 help -h
    check_case version 0 version --version
    check_case surface 0 surface --surface
    check_case demo 0 demo --demo
    check_case unknown 2 error 'synthetic-secret-do-not-echo'
    check_case empty 2 error ''
    check_case excess-help 2 error --help extra
    check_case excess-version 2 error --version extra
    check_case excess-demo 2 error --demo extra
    check_case excess-surface 2 error --surface extra
    printf 'PASS CLI %s: 12 cases\n' "$route"
    if [[ "$route" == "vm" ]]; then
        route_command=("$enigma_sdk_directory/nilinterpreter" "$enigma_project_root/ext/enigma-client/build/enigma-client-example.nil")
    else
        route_command=("$enigma_project_root/ext/enigma-client/build/enigma-client-example")
    fi
    check_case client-example 0 client-example
    printf 'PASS package example %s\n' "$route"
done

recovery_routes="$(IFS=,; printf '%s' "${routes[*]}")"
ENIGMA_TEST_TARGETS="$recovery_routes" NIL_SDK="$enigma_sdk_directory" \
    python3 -m unittest discover -s "$enigma_project_root/tests" -p 'test_*.py' -v
