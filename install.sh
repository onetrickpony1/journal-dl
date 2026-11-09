#!/bin/sh
# journal-dl installer for macOS and Linux. No admin rights needed.
#
#   curl -LsSf https://raw.githubusercontent.com/onetrickpony1/journal-dl/main/install.sh | sh
#
# What it does:
#   1. installs uv (https://docs.astral.sh/uv/) if missing: it manages Python for journal-dl
#   2. installs journal-dl in its own isolated environment, with its own Python if needed
#   3. puts journal-dl, ovid-dl, wiley-dl and tandf-dl on your PATH
#   4. downloads a private Chromium only if no Chrome, Chromium or Edge is installed
#   5. offers a "Journal Downloader" desktop icon
# Run it again to update. Uninstall: uv tool uninstall journal-dl
set -eu

SOURCE="${JOURNAL_DL_SOURCE:-journal-dl @ https://github.com/onetrickpony1/journal-dl/archive/refs/heads/main.zip}"
PYTHON="${JOURNAL_DL_PYTHON:-3.12}"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\njournal-dl installer: %s\n' "$*" >&2; exit 1; }
ask() {   # ask "question" default(y/n) -> 0 for yes; no terminal -> default
    if ( : < /dev/tty ) 2>/dev/null; then
        printf '%s ' "$1" > /dev/tty
        read -r ans < /dev/tty || ans=""
    else
        ans=""
    fi
    [ -z "$ans" ] && ans="$2"
    case "$ans" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

say "Installing journal-dl"

# 1. uv
if command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
else
    say "Installing uv (Python manager, from astral.sh)"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        fail "needs curl or wget to download uv"
    fi
    for c in "$HOME/.local/bin/uv" "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.cargo/bin/uv"; do
        [ -x "$c" ] && UV="$c" && break
    done
    [ -n "${UV:-}" ] || fail "uv was installed but can't be found; open a new terminal and run this again"
fi

# 2. journal-dl (+ Python if needed)
say "Installing journal-dl and its packages (Python $PYTHON is downloaded if needed)"
"$UV" tool install --force --python "$PYTHON" "$SOURCE" || fail "installing journal-dl failed (see above)"

# 3. PATH
"$UV" tool update-shell >/dev/null 2>&1 || true
BIN="$("$UV" tool dir --bin)"
JDL="$BIN/journal-dl"
[ -x "$JDL" ] || fail "journal-dl was installed but $JDL is missing"

# 4. browser
say "Checking for a browser"
"$JDL" --install-browser || printf 'Could not set up a browser automatically; install Google Chrome, then run: journal-dl --doctor\n'

# 5. desktop icon
if [ -z "${CI:-}" ] && ask "Add a 'Journal Downloader' icon to the desktop? [Y/n]" y; then
    "$JDL" --install-launcher || true
fi

say "Done: $("$JDL" --version)"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) printf 'Open a NEW terminal so the commands are found (they are in %s).\n' "$BIN" ;;
esac
cat <<'EOF'

Start with:   journal-dl --easy        (step-by-step guide; asks for your library details first)
Check setup:  journal-dl --doctor
Read first:   https://github.com/onetrickpony1/journal-dl/blob/main/LEGAL.md
EOF
