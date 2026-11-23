#!/usr/bin/env bash
# GitHub Repository Manager & Bulk Folder Uploader - dependency checker / installer
# Usage:  bash install.sh        (asks before installing anything)
#         bash install.sh -y     (answers "yes" to every question)
# License: BSD 3-Clause (full text in README.md)

set -u

ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            echo "Usage: bash install.sh [-y|--yes]"
            echo "  Checks for python, git, CA certificates and storage permission,"
            echo "  asks before installing anything, then prepares github.py."
            exit 0 ;;
        *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
    esac
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    G=$'\033[92m'; W=$'\033[97m'; R=$'\033[91m'; Y=$'\033[93m'; B=$'\033[1m'; X=$'\033[0m'
else
    G=""; W=""; R=""; Y=""; B=""; X=""
fi

ok()   { printf '%s%s[  OK  ]%s %s%s%s\n'  "$G" "$B" "$X" "$G" "$1" "$X"; }
bad()  { printf '%s%s[ FAIL ]%s %s%s%s\n'  "$R" "$B" "$X" "$R" "$1" "$X"; }
warn() { printf '%s%s[ WARN ]%s %s%s%s\n'  "$Y" "$B" "$X" "$Y" "$1" "$X"; }
info() { printf '%s%s[ INFO ]%s %s%s%s\n'  "$W" "$B" "$X" "$W" "$1" "$X"; }

ask_yes() {  # ask_yes "question" -> 0 for yes, 1 for no (default yes)
    if [ "$ASSUME_YES" -eq 1 ]; then return 0; fi
    local reply=""
    printf '%s%s%s %s[Y/n]%s ' "$G" "$1" "$X" "$W" "$X"
    read -r reply || reply="n"
    case "$reply" in ""|y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

printf '\n%s%s=== GitHub Repository Manager - Installer ===%s\n\n' "$G" "$B" "$X"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IN_TERMUX=0
case "${PREFIX:-}" in *com.termux*) IN_TERMUX=1 ;; esac

if [ "$IN_TERMUX" -eq 1 ]; then
    ok "Running inside Termux"
else
    warn "Termux was not detected. Dependencies are checked, but nothing can be auto-installed."
fi

# --------------------------------------------------------------- packages
install_pkg() {  # install_pkg <pkg> <why>
    local pkg="$1" why="$2"
    warn "$pkg is missing ($why)"
    if [ "$IN_TERMUX" -ne 1 ]; then
        info "Please install '$pkg' with your system package manager, then run this script again."
        return 1
    fi
    if ask_yes "Install '$pkg' now with 'pkg install $pkg'?"; then
        if pkg install -y "$pkg"; then
            ok "$pkg installed"
            return 0
        fi
        bad "Installing $pkg failed. Try: pkg update && pkg install $pkg"
        return 1
    fi
    warn "Skipped installing $pkg"
    return 1
}

FAILED=0

PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python >/dev/null 2>&1; then PY="python"; fi
if [ -z "$PY" ]; then
    if install_pkg python "needed to run github.py"; then PY="python"; else FAILED=1; fi
fi
if [ -n "$PY" ]; then
    if "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        ok "Python $("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    else
        bad "Python 3.8 or newer is required"
        FAILED=1
    fi
fi

if command -v git >/dev/null 2>&1; then
    ok "$(git --version)"
else
    install_pkg git "needed to stage, commit and push" || FAILED=1
fi

if [ "$IN_TERMUX" -eq 1 ]; then
    if [ -s "${PREFIX}/etc/tls/cert.pem" ] || [ -d "${PREFIX}/etc/tls/certs" ]; then
        ok "CA certificates present"
    else
        install_pkg ca-certificates "needed for HTTPS connections to GitHub" || FAILED=1
    fi

    if command -v termux-setup-storage >/dev/null 2>&1; then
        ok "termux-tools available"
    else
        install_pkg termux-tools "provides termux-setup-storage" || true
    fi

    if ls "$HOME/storage/shared" >/dev/null 2>&1; then
        ok "Internal storage access granted"
    else
        warn "Internal storage access has not been granted yet"
        if command -v termux-setup-storage >/dev/null 2>&1 && \
           ask_yes "Run 'termux-setup-storage' now? (Android will show a permission dialog)"; then
            termux-setup-storage
            for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
                ls "$HOME/storage/shared" >/dev/null 2>&1 && break
                sleep 0.5
            done
            if ls "$HOME/storage/shared" >/dev/null 2>&1; then
                ok "Internal storage access granted"
            else
                warn "Still no access - tap 'Allow' in the Android dialog, then re-run this installer"
            fi
        else
            warn "Skipped. Folders on internal storage cannot be read until permission is granted."
        fi
    fi
fi

# --------------------------------------------------------------- app files
APP="$SCRIPT_DIR/github.py"
if [ ! -f "$APP" ]; then
    bad "github.py was not found next to install.sh ($SCRIPT_DIR)"
    exit 1
fi
if [ -n "$PY" ] && "$PY" -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$APP" 2>/dev/null; then
    ok "github.py is valid"
else
    bad "github.py could not be verified"
    FAILED=1
fi
chmod +x "$APP" 2>/dev/null || true

# --------------------------------------------------------------- shortcut
if [ "$IN_TERMUX" -eq 1 ] && [ -n "$PY" ] && [ -d "${PREFIX}/bin" ]; then
    LAUNCHER="${PREFIX}/bin/github-manager"
    if ask_yes "Create the shortcut command 'github-manager' so you can start the app from anywhere?"; then
        printf '#!/usr/bin/env bash\nexec %s "%s" "$@"\n' "$PY" "$APP" > "$LAUNCHER" \
            && chmod +x "$LAUNCHER" \
            && ok "Shortcut created: run  github-manager" \
            || warn "Could not create the shortcut"
    fi
fi

# --------------------------------------------------------------- summary
echo
if [ "$FAILED" -eq 0 ]; then
    printf '%s%s[ SUCCESS ]%s %sInstallation complete. Start the app with:%s\n\n' "$G" "$B" "$X" "$G" "$X"
    printf '    %s%spython %s%s\n\n' "$W" "$B" "$APP" "$X"
    exit 0
fi
printf '%s%s[ FAILED ]%s %sSome requirements are missing. Fix the items above and run:  bash install.sh%s\n\n' "$R" "$B" "$X" "$R" "$X"
exit 1
