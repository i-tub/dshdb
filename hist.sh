#!/bin/bash

# Distributed Shell History Database (dshdb)
#
# This script must be sourced to enable keeping track of history and computing
# elapsed time.
#
# For more information and updates, see https://github.com/i-tub/dshdb .

export HIST_SESSION_ID=$(python -c 'import uuid; print uuid.uuid4().hex[:16]')

hist_in_cmd=0

function hist_pre_cmd() {
    hist_in_cmd=1
    hist_pwd="$PWD"
    hist_timestamp=$SECONDS
    VISUAL="$VISUAL_ORIG"
}

function hist_post_cmd() {
    local status=$?
    local n=${1:-1}
    if [ "$hist_in_cmd" -eq 1 ]; then
        hist_elapsed=$(($SECONDS - $hist_timestamp))
        HISTTIMEFORMAT='%s%t' history $n | python ~/.hist/hist.py \
        --import_hist --dir "$hist_pwd" --elapsed "$hist_elapsed" \
        --session . --hostname . --status $status
    else
        hist_elapsed=0
    fi
    hist_in_cmd=0
    VISUAL=vimwrap
}

# Hack to support edit-and-execute-command (C-xC-e by default). The command is
# executed by readline which just redraws the prompt without calling
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

