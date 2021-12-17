# Distributed shell history database

Have you ever asked yourself "how did I run that obscure command with a
bajillion argument 5 years ago, and where?" And wished that the incantation
had been preserved in your shell history?

While you can configure bash to keep unlimited history, there are still some
caveats, namely the lack of concept of session and the lack of working
directory information. If you have more than one shell open, history can get
confusing. And if you work on multiple hosts, even more so.

The Distributed Shell History Database, dshdb, keeps your history forever in
an sqlite database; preserves metadata such as session, CWD, hostname, elapsed
time, and exit status; makes searching the database easy; and finally, makes
it easy to synchronize the databases between multiple hosts.

It is written in Python 2, because unfortunately many Linux distributions
still in use don't have Python 3 out of the box, and I wanted to minimize
dependencies. Hooks for bash are provided, but I think it should be easy to
get it to work for zsh.

## Installation

First, put hist.py anywhere on your path and make sure it's executable; add
hist.sh wherever you like (suggested place: ~/.hist.sh).

Then, for bash, install
[Bash-Preexec](https://github.com/rcaloras/bash-preexec), and add a line at
the bottom of your .bashrc to source hist.sh:

```
. ~/.hist.sh
```

## Examples

The default invocation just shows the last 30 commands in reverse chronological
order.

```
$ hist.py
2021-12-07T09:35:20	ls
2021-12-07T09:35:02	git log
...
```
