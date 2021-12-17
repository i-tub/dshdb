#!/bin/bash

# This script must be sourced to enable keeping track of history and computing
# elapsed time.

hist_start_time=$(( `date +%s` - $SECONDS ))

export HIST_SESSION_ID=$(python -c 'import uuid; print uuid.uuid4()')

hist_in_cmd=0

function pre_cmd() {
    hist_in_cmd=1
    hist_pwd="$PWD"
    hist_timestamp=$(( $hist_start_time + $SECONDS ))
}

function post_cmd() {
    if [ "$hist_in_cmd" -eq 1 ]; then
        hist_elapsed=$(($SECONDS + $hist_start_time - $hist_timestamp))
        python ~/bin/append_hist.py --insert $HIST_SESSION_ID \
            "$hist_pwd" "$hist_timestamp" "$hist_elapsed" \
            "$(HISTTIMEFORMAT='' history 1 | sed 's/^ *[0-9]* *//')"
    else
        hist_elapsed=0
    fi
    hist_in_cmd=0
}

# Register functions with ~/.bash-preexec.sh
precmd_functions+=post_cmd
preexec_functions+=pre_cmd

