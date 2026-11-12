#!/usr/bin/env bash
set -euo pipefail

main() {
    local -a packages=("$@")

    if (( ${#packages[@]} == 0 )); then
        echo "usage: $0 PACKAGE [PACKAGE...]" >&2
        return 2
    fi

    configure_apt

    if ! timeout 10 getent hosts archive.ubuntu.com >/dev/null 2>&1 \
        || ! timeout 10 getent hosts security.ubuntu.com >/dev/null 2>&1; then
        echo "warning: an Ubuntu archive host does not resolve; using the kernel.org mirror" >&2
        use_fallback_mirror
    fi

    if apt_update && apt_install "${packages[@]}"; then
        return 0
    fi

    echo "warning: apt update/install failed; retrying with the kernel.org Ubuntu mirror" >&2

    use_fallback_mirror

    apt_update
    apt_install "${packages[@]}"
}

configure_apt() {
    local conf=/etc/apt/apt.conf.d/99cecli-retries
    local tmp

    tmp=$(mktemp)

    cat >"$tmp" <<'EOF'
Acquire::Retries "3";
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "10";
Acquire::https::Timeout "10";
EOF

    sudo install -m 0644 "$tmp" "$conf"
    rm -f "$tmp"
}

apt_update() {
    sudo apt-get update
}

apt_install() {
    sudo apt-get install -y --no-install-recommends "$@"
}

use_fallback_mirror() {
    local mirror=https://mirrors.edge.kernel.org/ubuntu
    local -a targets=()
    local path

    if [[ -f /etc/apt/sources.list ]]; then
        targets+=(/etc/apt/sources.list)
    fi

    while IFS= read -r path; do
        targets+=("$path")
    done < <(find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) 2>/dev/null | sort)

    if (( ${#targets[@]} > 0 )); then
        sudo find "${targets[@]}" -type f -exec sed -i -E \
            -e "s#https?://[A-Za-z0-9._-]*\.ubuntu\.com/ubuntu#${mirror}#g" \
            -e "s#mirror\+file:/etc/apt/apt-mirrors\.txt#${mirror}#g" {} +
    fi

    if ! grep -rqE 'apt-mirrors\.txt' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
        sudo rm -f /etc/apt/apt-mirrors.txt
    fi
}

main "$@"
