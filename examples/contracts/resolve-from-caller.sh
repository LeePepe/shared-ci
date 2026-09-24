#!/bin/sh
# Tools, this script, resolver bytes and distribution must already be admitted.
if [ "$#" -ne 7 ] || [ "$1" != '--python' ] || [ "$3" != '--git' ]; then
    printf '%s\n' 'usage: resolve-from-caller.sh --python ABSOLUTE_PYTHON --git ABSOLUTE_GIT PROVIDER_DIR FULL_SHA ENTRY_ID' >&2
    exit 2
fi
case "$2" in /*) ;; *) printf '%s\n' 'error: Python path must be absolute' >&2; exit 2 ;; esac
case "$4" in /*) ;; *) printf '%s\n' 'error: Git path must be absolute' >&2; exit 2 ;; esac
case "$5" in /*) ;; *) printf '%s\n' 'error: provider path must be absolute' >&2; exit 2 ;; esac
exec "$2" -I -S -B "$5/scripts/contracts/resolve.py" --git "$4" --revision "$6" --entry "$7"
