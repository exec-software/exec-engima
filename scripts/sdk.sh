#!/usr/bin/env bash
# Shared SDK discovery; source this file and call enigma_setup_sdk.

enigma_setup_sdk() {
    enigma_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    enigma_sdk_directory=""

    if [[ -n "${NIL_SDK:-}" ]]; then
        if [[ ! -d "$NIL_SDK" ]]; then
            printf 'NIL_SDK must name an existing SDK directory.\n' >&2
            return 2
        fi
        enigma_sdk_directory="$(cd -- "$NIL_SDK" && pwd)"
    elif [[ -x "$enigma_project_root/.sdk/nilbuild" ]]; then
        enigma_sdk_directory="$(cd -- "$enigma_project_root/.sdk" && pwd)"
    elif [[ -x "$enigma_project_root/../exec-nil-framework/sdk/nilbuild" ]]; then
        enigma_sdk_directory="$(cd -- "$enigma_project_root/../exec-nil-framework/sdk" && pwd)"
    elif command -v nilbuild >/dev/null 2>&1; then
        local builder_path
        builder_path="$(command -v nilbuild)"
        enigma_sdk_directory="$(cd -- "$(dirname -- "$builder_path")" && pwd)"
    else
        printf 'NIL SDK not found. Set NIL_SDK; see docs/development.md.\n' >&2
        return 2
    fi

    local tool_name
    for tool_name in nilbuild nilcompiler nilinterpreter niltest; do
        if [[ ! -x "$enigma_sdk_directory/$tool_name" ]]; then
            printf 'SDK is missing executable %s. Set NIL_SDK to a complete SDK.\n' "$tool_name" >&2
            return 2
        fi
    done

    export NIL_STRICT_BOUNDS=1
}
