#!/bin/bash

# Distributed Shell History Database (dshdb)
#
# This script must be sourced to enable keeping track of history and computing
# elapsed time. It requires that bash-preexec.sh be sourced first.
#
# For more information and updates, see https://github.com/i-tub/dshdb .

# Set HIST_DIR to directory containing this script, unless already defined.
export HIST_DIR="${HIST_DIR:-${BASH_SOURCE%/*}}"

# Prepend HIST_DIR to PATH unless already there.
case ":$PATH:" in
    *":$HIST_DIR:"*) ;;
    *) export PATH="$HIST_DIR:$PATH" ;;
esac

export HIST_SESSION_ID=$(python -c 'from __future__ import print_function; import sys; sys.path.pop(0); import uuid; print(uuid.uuid4().hex[:16])')

__hist_in_cmd=0

# Keep track of when a command started executing and where. This is installed
# as a preexec function with bash-preexec.sh.
function hist_preexec() {
    # Keep track of the fact that we are starting a command, because
    # hist_precmd gets called even when hitting enter without any command.
    __hist_in_cmd=1
    __hist_pwd="$PWD"
    __hist_timestamp=$SECONDS
    # Restore original VISUAL so it's accessible by the program being run.
    VISUAL="$VISUAL_ORIG"
}

# Add a new entry to the history database. This is installed as a precmd
# function with bash-preexec.sh.
function hist_precmd() {
    local status=$?  # Status of command to store in db
    local n=${1:-1}  # Number of history lines to import
    if [ "$__hist_in_cmd" -eq 1 ]; then
        # Compute elapsed time and store it in a global variable so users
        # can include it in their PS1 if they wish.
        hist_elapsed=$(($SECONDS - $__hist_timestamp))
        HISTTIMEFORMAT='%s%t' history $n | hist.py --import_hist \
            --dir "$__hist_pwd" --elapsed "$hist_elapsed" \
            --session . --hostname . --status $status
    else
        hist_elapsed=0
    fi
    __hist_in_cmd=0
    VISUAL=vimwrap
}

# Hack to support edit-and-execute-command (C-xC-e by default). The command is
# executed by readline which then redraws the prompt without running
# $PROMPT_COMMAND. The workaround here is to use a bash function for $VISUAL,
# and have this function ensure that hist_preexec and hist_precmd get called.
# hist_preexec temporarily sets $VISUAL back to its original value so that
# programs that depend on it (e.g., git) can get a real program to run as an
# editor. Also, since we actually add hist_precmd to the tmpfile written by
# the editor, we need to use HISTIGNORE to prevent it from polluting the
# history.
VISUAL_ORIG="$VISUAL"
VISUAL=vimwrap
HISTIGNORE="$HISTIGNORE:hist_preexec:hist_precmd*"

function vimwrap () {
    $VISUAL_ORIG "$1"
    hist_preexec
    echo "hist_precmd $(wc -l < "$1")" >> "$1"
}


# Register functions with ~/.bash-preexec.sh
precmd_functions+=hist_precmd
preexec_functions+=hist_preexec

