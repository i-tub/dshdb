# Distributed shell history database

Have you ever asked yourself "how did I run that obscure command with a
bajillion arguments 5 years ago, and where?" And wished that the incantation
had been preserved in your shell history?

While you can configure bash to keep a very long history, there are still some
caveats, namely the lack of concept of session and the lack of working
directory information. If you have more than one shell open, history can get
confusing. And if you work on multiple hosts, even more so. Finally, bash
history files are surprisingly easy to clobber by accident.

The Distributed Shell History Database, dshdb, keeps your history forever in an
sqlite database; preserves metadata such as session, CWD, hostname, elapsed
time, and exit status; makes searching the database easy; and finally, makes it
easy to synchronize the databases between multiple hosts.

It is written for Python 2 and 3, since many Linux distributions still in use
only have Python 2 by default. Hooks for bash are provided; I think it's not
too difficult to adapt them to zsh, but I don't use zsh. If you get it working,
please send it along!

## Installation

First, install [Bash-Preexec](https://github.com/rcaloras/bash-preexec). This
is the only dependency (not counting Python and bash!).

Then, run `make install` to copy the scripts to ~/.hist. You can choose a
different location by adding `HIST_DIR=<your_location>` when running make. This
directory will also be the location of the history database file, `hist.db`.

Finally, add a line at the bottom of your .bashrc to source hist.sh; for
example, if you used the default location,

```
. ~/.hist/hist.sh
```

Optional: define a more convenient alias. I have `alias hi=hist.py`.

## Examples

The default invocation just shows the last 30 commands in reverse chronological
order, showing timestamp and command.

```
$ hist.py
2021-12-07T09:35:20	ls
2021-12-07T09:35:02	git log
...
```

### Searching

You can constrain the output to a given directory or session, search for a
command substring, search by exit status or elapsed time. See the help message
for details. For example, let's search for `make` commands in the current
directory with a nonzero exit status:

```
$ hist.py -d . -x '!= 0' make
2021-12-15T11:01:35	make test
2021-12-15T10:50:59	make
2021-12-14T10:45:46	make
...
```

### Output format

You can also control the output format to choose which columns are included in
the tab-delimited output. For example, to show directory, elapsed time, exit
status, and command.

```
$ hist.py -fdexc
~/hist	0	1	false
~/hist	0	0	true
~/hist	3	0	sleep 3
...
```

### Synchronizing with a remote host

To synchronize your database with your database on example.com, simply say

```
$ hist.py --sync example.com
```

Note that the syncronization goes both ways!

### Importing your existing bash history

```
HISTTIMEFORMAT="%s%t" history | hist.py
```

## Bugs

Timestamps have 1-second resolution; if you run the same command twice within
the same second on the same directory, hostname, shell session, with the same
elapsed time and exit status, it will be inserted into the database only once.

If you use the edit-and-execute-command readline binding in bash (C-xC-e by
default) to run commands in multiple lines, all of them will end up with the
same metadata, other than the timestamp. For example, if your edited command is

    sleep 1
    sleep 2
    false

all three commands will be recorded with an elapsed time of 3 seconds and exit
status 1.

## Similar projects

After I started this project, I came to realize that there were a couple of
similar projects already out there:
[Bashhub](https://github.com/rcaloras/bashhub-client) and
[RASH](https://github.com/tkf/rash). They may be more featureful and polished,
doing things such as interactive search or uploading your history to the cloud.
My approach is more minimalistic, and I don't plan to add those features. I
also tried to minimize the dependencies so that the only thing you need to
install is a python script and a shell script. It works exactly the way I want.
This is my wheel. There are many like it, but this one is mine! :-)
