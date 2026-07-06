#!/usr/bin/env bash
set -euo pipefail

REPO="${SNAPSHOT_REPO:-https://github.com/codingsushi79/Snapshot.git}"
REF="${SNAPSHOT_REF:-main}"
INSTALL_SPEC="git+${REPO}@${REF}"

info() { printf '\033[1;34m→\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

find_python() {
  for cmd in python3 python py; do
    if need_cmd "$cmd"; then
      if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

ensure_pip() {
  local py="$1"
  if "$py" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  info "Bootstrapping pip…"
  "$py" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$py" -m pip --version >/dev/null 2>&1
}

pip_user_flag() {
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo ""
  else
    echo "--user"
  fi
}

install_with_pipx() {
  local py="$1"
  info "Installing snapshot with pipx…"
  if ! need_cmd pipx; then
    local user_flag
    user_flag="$(pip_user_flag)"
    # shellcheck disable=SC2086
    "$py" -m pip install $user_flag pipx
    export PATH="${HOME}/.local/bin:${PATH}"
    if need_cmd pipx; then
      pipx ensurepath >/dev/null 2>&1 || true
    fi
  fi
  if need_cmd pipx; then
    pipx install --force "$INSTALL_SPEC"
    return 0
  fi
  return 1
}

install_with_pip() {
  local py="$1"
  local user_flag
  user_flag="$(pip_user_flag)"
  info "Installing snapshot with pip…"
  # shellcheck disable=SC2086
  "$py" -m pip install $user_flag --upgrade "$INSTALL_SPEC"
}

verify_install() {
  export PATH="${HOME}/.local/bin:${HOME}/Library/Python/3.12/bin:${HOME}/Library/Python/3.11/bin:${HOME}/Library/Python/3.10/bin:${PATH}"
  if command -v snapshot >/dev/null 2>&1; then
    info "Installed: $(snapshot --version 2>/dev/null || snapshot --help | head -1)"
    info "Run: snapshot https://example.com ./mirror"
    return 0
  fi
  warn "snapshot installed, but not on PATH."
  warn "Add this to your shell profile:"
  echo "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  return 1
}

main() {
  info "Installing snapshot from ${INSTALL_SPEC}"

  if ! PY="$(find_python)"; then
    err "Python 3.10+ is required."
    err "Install Python from https://www.python.org/downloads/ and re-run this script."
    exit 1
  fi

  if ! ensure_pip "$PY"; then
    err "pip is required but could not be installed."
    exit 1
  fi

  if ! install_with_pipx "$PY"; then
    install_with_pip "$PY"
  fi

  verify_install || true
}

main "$@"
