"""
Create a history database from stdin, which must have the format

    <timestamp><tab><idx><spaces><command>

where timestamp is number of seconds since the epoch.

In bash, simply run

    HISTTIMEFORMAT='%s%t' history
"""
import argparse
import collections
import sqlite3
import socket
import sys
import datetime as dt


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('hist_file')
    return parser.parse_args()


Entry = collections.namedtuple('Entry', 'session pwd raw_timestamp elapsed cmd hostname')

INSERT = 'INSERT INTO hist (session, pwd, timestamp, elapsed, cmd, hostname) ' \
         'VALUES (?,?,?,?,?,?)'


def read_hist(fh):
    hostname = socket.gethostname()
    for i, line in enumerate(fh, 1):
        try:
            idx_timestamp, cmd = line.split('\t', 1)
            cmd = cmd.rstrip()
            idx, timestamp_str = idx_timestamp.split()
            raw_timestamp = int(timestamp_str)
        except ValueError:
            sys.exit('bad line {}: >>>{}<<<'.format(i, line))
        if sys.version_info.major < 3:
            cmd = cmd.decode('utf8')
        yield Entry('', '', raw_timestamp, 0, cmd, hostname)


def main():
    args = parse_args()
    conn = sqlite3.connect(args.hist_file)
    with conn:
        conn.execute('DROP TABLE IF EXISTS hist')
        conn.execute('CREATE TABLE hist (session TEXT, pwd TEXT, '
                     'timestamp INTEGER, elapsed INTEGER, cmd TEXT, '
                     'hostname TEXT)')
        conn.execute('CREATE INDEX ts_idx ON hist (timestamp DESC)')
        for e in read_hist(sys.stdin):
            conn.execute(INSERT,
                         (e.session, e.pwd, e.raw_timestamp, e.elapsed, e.cmd,
                          e.hostname))
    conn.close()


if __name__ == '__main__':
    main()
