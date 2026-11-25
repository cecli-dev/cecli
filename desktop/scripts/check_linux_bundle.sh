#!/usr/bin/env bash
# Verify that the built Linux bundles expose /usr/bin/ce-underscore.
#
# Tauri installs the main binary there when productName is ce-underscore. This
# script only inspects artifacts; it never installs or runs the app.
#
#   check_linux_bundle.sh [bundle-dir]
#
# bundle-dir defaults to target/release/bundle at the repository root. Missing
# package types are skipped with a warning so the script works for partial
# builds.

main() {
  set -euo pipefail

  local bundle_dir="${1:-target/release/bundle}"
  local failures=0

  local checker result
  for checker in check_deb check_appimage check_rpm; do
    result=0
    "$checker" "$bundle_dir" || result=$?
    failures=$((failures + result))
  done

  if [[ "$failures" -ne 0 ]]; then
    printf 'error: %s bundle(s) do not expose /usr/bin/ce-underscore\n' "$failures" >&2
    return 1
  fi

  printf 'all inspected bundles expose /usr/bin/ce-underscore\n'
}

check_deb() {
  local bundle_dir="$1"
  local deb
  deb="$(first_match "$bundle_dir/deb/*.deb")"

  if [[ -z "$deb" ]]; then
    printf 'warning: no deb under %s/deb; skipping\n' "$bundle_dir" >&2
    return 0
  fi

  if ! command -v dpkg-deb >/dev/null 2>&1; then
    printf 'warning: dpkg-deb is unavailable; cannot inspect %s\n' "$deb" >&2
    return 0
  fi

  if dpkg-deb --contents "$deb" | grep -qE '(^|/)usr/bin/ce-underscore$'; then
    printf 'deb ok: %s\n' "$deb"
    return 0
  fi

  printf 'error: %s has no /usr/bin/ce-underscore\n' "$deb" >&2
  return 1
}

check_appimage() {
  local bundle_dir="$1"
  local appimage
  appimage="$(first_match "$bundle_dir/appimage/*.AppImage")"

  if [[ -z "$appimage" ]]; then
    printf 'warning: no AppImage under %s/appimage; skipping\n' "$bundle_dir" >&2
    return 0
  fi

  local extract_dir
  extract_dir="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$extract_dir'" RETURN

  if ! (cd "$extract_dir" && "$appimage" --appimage-extract >/dev/null 2>&1); then
    printf 'warning: could not extract %s; skipping\n' "$appimage" >&2
    return 0
  fi

  if [[ -x "$extract_dir/squashfs-root/usr/bin/ce-underscore" ]]; then
    printf 'AppImage ok: %s\n' "$appimage"
    return 0
  fi

  printf 'error: %s has no usr/bin/ce-underscore\n' "$appimage" >&2
  return 1
}

check_rpm() {
  local bundle_dir="$1"
  local rpm
  rpm="$(first_match "$bundle_dir/rpm/*.rpm")"

  if [[ -z "$rpm" ]]; then
    printf 'warning: no rpm under %s/rpm; skipping\n' "$bundle_dir" >&2
    return 0
  fi

  if ! command -v rpm >/dev/null 2>&1; then
    printf 'warning: rpm is unavailable; cannot inspect %s\n' "$rpm" >&2
    return 0
  fi

  if rpm -qlp "$rpm" | grep -qE '^/usr/bin/ce-underscore$'; then
    printf 'rpm ok: %s\n' "$rpm"
    return 0
  fi

  printf 'error: %s has no /usr/bin/ce-underscore\n' "$rpm" >&2
  return 1
}

first_match() {
  local pattern="$1"
  local matches

  # shellcheck disable=SC2086
  matches=( $pattern )
  if [[ "${#matches[@]}" -eq 0 || ! -e "${matches[0]}" ]]; then
    return 0
  fi

  printf '%s\n' "${matches[0]}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
