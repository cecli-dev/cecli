#!/usr/bin/env bash
# Stop the app-harness bridge before an update replaces files, then verify that
# bridge.json still describes the binary that is now installed.
#
# Run directly or source this file to call the functions:
#
#   stop_bridge_before_update   stop the bridge; "no bridge" is success
#   verify_bridge_version       fail when bridge.json.version != --version
#
# `ce-underscore --stop-bridge` exits 0 both when it stopped a bridge and when
# no bridge was running, so a missing binary is also treated as success: a
# pip-only cecli install has no desktop app and nothing to stop.
#
# Platform hooks:
# - Windows: referenced from tauri.release.conf.json through nsis-hooks.nsh.
# - Linux: referenced from tauri.release.conf.json as the deb/rpm maintainer
#   script. dpkg/rpm invoke it as root, so the bridge file is resolved for
#   SUDO_USER when present. Unknown maintainer arguments fall through to "all".
# - macOS: the .dmg has no pre-install hook. The cask template in brew-cask/
#   calls stop_bridge_before_update in `preflight` and verify_bridge_version in
#   `postflight`; a .pkg postinstall must do the same before/after replacing
#   ce-underscore.app.

bridge_file_path() {
  if [[ -n "${CECLI_BRIDGE_FILE:-}" ]]; then
    printf '%s\n' "$CECLI_BRIDGE_FILE"
    return
  fi

  local home_dir
  home_dir="$(effective_home)"

  case "$(uname -s)" in
    Darwin)
      printf '%s\n' "$home_dir/Library/Application Support/cecli/bridge.json"
      ;;
    Linux)
      local runtime
      runtime="$(runtime_dir)"
      if [[ -n "$runtime" && -d "$runtime" ]]; then
        printf '%s\n' "$runtime/cecli/bridge.json"
      else
        printf '%s\n' "$home_dir/.cache/cecli/bridge.json"
      fi
      ;;
    *)
      printf '%s\n' "${LOCALAPPDATA:-$home_dir}/cecli/bridge.json"
      ;;
  esac
}

underscore_binary() {
  if [[ -n "${CECLI_DESKTOP_BIN:-}" ]]; then
    printf '%s\n' "$CECLI_DESKTOP_BIN"
    return
  fi

  local candidates=()
  case "$(uname -s)" in
    Darwin)
      candidates+=("/Applications/ce-underscore.app/Contents/MacOS/ce-underscore")
      ;;
    Linux)
      candidates+=("/usr/bin/ce-underscore" "/usr/local/bin/ce-underscore")
      ;;
  esac

  local on_path
  on_path="$(command -v ce-underscore 2>/dev/null || true)"
  [[ -n "$on_path" ]] && candidates+=("$on_path")

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  return 1
}

stop_bridge_before_update() {
  local binary status=0
  binary="$(underscore_binary || true)"

  if [[ -z "$binary" ]]; then
    printf 'ce-underscore is not installed; no bridge to stop\n'
    return 0
  fi

  printf 'stopping the app-harness bridge via %s\n' "$binary"
  "$binary" --stop-bridge >/dev/null 2>&1 || status=$?

  if [[ "$status" -eq 0 ]]; then
    return 0
  fi

  local file
  file="$(bridge_file_path)"
  if [[ ! -f "$file" ]]; then
    printf 'ce-underscore --stop-bridge exited %s; no %s, treating as "no bridge"\n' \
      "$status" "$file" >&2
    return 0
  fi

  printf 'error: failed to stop the app-harness bridge (exit %s)\n' "$status" >&2
  return "$status"
}

verify_bridge_version() {
  local file bridge_version
  file="$(bridge_file_path)"

  if [[ ! -f "$file" ]]; then
    printf 'no %s; nothing to verify\n' "$file"
    return 0
  fi

  bridge_version="$(stored_bridge_version "$file")"
  if [[ -z "$bridge_version" ]]; then
    printf 'warning: %s has no readable version; skipping the skew check\n' "$file" >&2
    return 0
  fi

  local binary new_version
  binary="$(underscore_binary || true)"
  if [[ -z "$binary" ]]; then
    printf 'error: cannot verify the bridge version: ce-underscore is not installed\n' >&2
    return 4
  fi

  new_version="$(binary_version "$binary")"
  if [[ -z "$new_version" ]]; then
    printf 'error: %s --version did not report a version\n' "$binary" >&2
    return 4
  fi

  if [[ "$bridge_version" != "$new_version" ]]; then
    printf 'version skew: %s reports %s but %s reports %s\n' \
      "$file" "$bridge_version" "$binary" "$new_version" >&2
    printf 'The old bridge was not stopped before its files were replaced. Run:\n' >&2
    printf '  ce-underscore --stop-bridge\n' >&2
    printf 'then start the bridge again with:\n' >&2
    printf '  ce-underscore --ensure-bridge\n' >&2
    return 3
  fi

  printf 'bridge version %s matches %s\n' "$new_version" "$binary"
}

usage() {
  cat >&2 <<'EOF'
usage: stop_bridge_before_update.sh [stop|verify|all]

  stop    stop a running bridge; a missing bridge is success
  verify  fail when bridge.json.version differs from ce-underscore --version
  all     stop, then verify (default; also what dpkg/rpm invoke)
EOF
}

main() {
  set -euo pipefail

  local action="all"
  case "${1:-}" in
    stop | verify | all)
      action="$1"
      ;;
    -h | --help)
      usage
      return 0
      ;;
  esac

  case "$action" in
    stop) stop_bridge_before_update ;;
    verify) verify_bridge_version ;;
    all)
      stop_bridge_before_update
      verify_bridge_version
      ;;
  esac
}

effective_home() {
  local user_name="${SUDO_USER:-}"

  if [[ "$(id -u)" -eq 0 && -n "$user_name" && "$user_name" != "root" ]]; then
    local resolved
    resolved="$(getent passwd "$user_name" 2>/dev/null | cut -d: -f6 || true)"
    if [[ -n "$resolved" ]]; then
      printf '%s\n' "$resolved"
      return
    fi
  fi

  printf '%s\n' "$HOME"
}

runtime_dir() {
  if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    printf '%s\n' "$XDG_RUNTIME_DIR"
    return
  fi

  local user_name="${SUDO_USER:-}"
  if [[ "$(id -u)" -eq 0 && -n "$user_name" && "$user_name" != "root" ]]; then
    local uid
    uid="$(id -u "$user_name" 2>/dev/null || true)"
    if [[ -n "$uid" ]]; then
      printf '%s\n' "/run/user/$uid"
      return
    fi
  fi
}

stored_bridge_version() {
  local file="$1"
  sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -n 1
}

binary_version() {
  local binary="$1"
  "$binary" --version 2>/dev/null \
    | grep -oE '[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.]+)?' \
    | head -n 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
