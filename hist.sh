#!/bin/bash

# Distributed Shell History Database (dshdb)
#
# This script must be sourced to enable keeping track of history and computing
# elapsed time.
#
# For more information and updates, see https://github.com/i-tub/dshdb .

export HIST_SESSION_ID=$(python -c 'import sys; sys.path.pop(0); import uuid; print uuid.uuid4().hex[:16]')

__hist_in_cmd=0

function hist_pre_cmd() {
    # Keep track of the fact that we are starting a command, because
    # hist_post_cmd gets called even when hitting enter without any command.
    __hist_in_cmd=1
    __hist_pwd="$PWD"
    __hist_timestamp=$SECONDS
    # Restore original VISUAL so it's accessible by the program being run.
    VISUAL="$VISUAL_ORIG"
}

function hist_post_cmd() {
    local status=$?  # Status of command to store in db
    local n=${1:-1}  # Number of history lines to import
    if [ "$__hist_in_cmd" -eq 1 ]; then
        # Compute elapsed time and store it in a global variable so users
        # can include it in their PS1.
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
# and have this function ensure that hist_pre_cmd and hist_post_cmd get called.
# hist_pre_cmd temporarily sets $VISUAL back to its original value so that
# programs that depend on it (e.g., git) can get a real program to run as an
# editor. Also, since we actually add hist_post_cmd to the tmpfile written by
# the editor, we need to use HISTIGNORE to prevent it from polluting the
# history.
VISUAL_ORIG="$VISUAL"
VISUAL=vimwrap
HISTIGNORE="$HISTIGNORE:hist_pre_cmd:hist_post_cmd*"

function vimwrap () {
    $VISUAL_ORIG "$@"
    hist_pre_cmd
    echo "hist_post_cmd $(wc -l <$1)" >> $1
}


# Register functions with ~/.bash-preexec.sh
precmd_functions+=hist_post_cmd
preexec_functions+=hist_pre_cmd

