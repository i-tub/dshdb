#!/bin/bash

# This script must be sourced to enable keeping track of history and computing
# elapsed time.

export HIST_SESSION_ID=$(python -c 'import uuid; print uuid.uuid4().hex[:16]')

hist_in_cmd=0
hist_window=1
VISUAL_ORIG="$VISUAL"
HISTIGNORE="$HISTIGNORE:hist_pre_cmd:hist_post_cmd"

function hist_pre_cmd() {
    hist_in_cmd=1
    hist_pwd="$PWD"
    hist_timestamp=$SECONDS
    VISUAL="$VISUAL_ORIG"
}

function hist_post_cmd() {
    if [ "$hist_in_cmd" -eq 1 ]; then
        hist_elapsed=$(($SECONDS - $hist_timestamp))
        HISTTIMEFORMAT='%s%t' history $hist_window | python ~/.hist/hist.py \
        --import_hist --dir "$hist_pwd" --elapsed "$hist_elapsed" --session .
    else
        hist_elapsed=0
    fi
    hist_in_cmd=0
    VISUAL=vimwrap
}

function vimwrap () {
    $VISUAL_ORIG "$@"
    hist_pre_cmd
    echo "hist_post_cmd" >> $1
}

export VISUAL=vimwrap

# Register functions with ~/.bash-preexec.sh
precmd_functions+=hist_post_cmd
preexec_functions+=hist_pre_cmd

