#!/bin/env python
"""
Search or manipulate the distributed shell history database.

For more information and updates, see https://github.com/i-tub/dshdb .
"""

from __future__ import print_function

import argparse
import collections
import datetime
import hashlib
import json
import operator
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys

DEFAULT_HISTFILE = '~/.hist.db'
FIELDS = [
    'id', 'session', 'pwd', 'timestamp', 'elapsed', 'cmd', 'hostname',
    'status', 'idx'
]
# Fields are TEXT unless listed below.
INT_FIELDS = {'timestamp', 'elapsed', 'status', 'idx'}

Entry = collections.namedtuple('Entry', FIELDS)

# For use in --fmt argument.
COLS = {
    'i': 'id',
    's': 'session',
    'd': '~pwd',
    'D': 'pwd',
    't': 'timestamp',
    'e': 'elapsed',
    'c': 'cmd',
    'h': 'hostname',
    'x': 'status',
}
DEFAULT_FMT = 'thsdec'

PY2 = sys.version_info.major < 3

INSERT = 'INSERT OR IGNORE INTO hist ({}) VALUES ({})'.format(
    ','.join(FIELDS), ','.join(['?'] * len(FIELDS)))

HOME = os.path.expanduser('~')


class HistFormatter:

    def __init__(self, fmt, group=False):
        self.prev_date = None
        self.group = group
        self.field_getters = []

        for c in fmt or DEFAULT_FMT:
            col = COLS.get(c)
            if not col:
                continue
            elif col == 'timestamp':
                getter = lambda e: e.timestamp.isoformat()
            elif col == '~pwd':
                getter = lambda e: contractuser(e.pwd)
            else:
                getter = operator.attrgetter(col)
            self.field_getters.append(getter)

    def format(self, entry):
        ts = entry.timestamp
        date = ts.date().isoformat()
        if date != self.prev_date:
            self.prev_date = date
            if self.group:
                yield '{}:'.format(date)
        if self.group:
            ts = ts.time()
        fields = [g(entry) for g in self.field_getters]
        if self.group:
            fields.insert(0, '')
        if PY2:
            s = '\t'.join(map(unicode, fields))
            yield s.encode('utf8')
        else:
            yield '\t'.join(map(str, fields))


def contractuser(dirname):
    """
    Opposite of os.path.expanduser().
    """
    if dirname.startswith(HOME):
        return '~' + dirname[len(HOME):]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cmd',
                        nargs='?',
                        metavar='<like>',
                        help='Search by command.')
    parser.add_argument(
        '--session',
        '-s',
        metavar='<like>',
        help='Search by session ID. Use "." for current session.')
    parser.add_argument(
        '--dir',
        '-d',
        metavar='<like>',
        help='Search by directory. Use "." for current working directory.')
    parser.add_argument('--elapsed', '-e',
                        metavar='<int>',
        help='Elapsed time. May use a string with an operator (e.g., "> 10")')
    parser.add_argument('--status', '-x',
                        metavar='<int>|<op><int>',
        help='Exit status. May use a string with an operator (e.g., "> 0")')
    parser.add_argument(
        '--fmt',
        '-f',
        metavar='<fields>',
        default='tc',
        help='Format spec; a string of one-character field identifiers: '
        't=timestamp, h=hostname, s=session, d=pwd, e=elapsed, c=cmd. '
        'Default is "%(default)s". Use empty string for all.')
    parser.add_argument('--all',
                        '-a',
                        action='store_true',
                        help='Return all results.')
    parser.add_argument('--group',
                        '-g',
                        action='store_true',
                        help='Group results by date.')
    parser.add_argument(
        '-n',
        type=int,
        metavar='<int>',
        default=30,
        help='Number of results to return. Default=%(default)s.')
    parser.add_argument('--dedup',
                        '-u',
                        action='store_true',
                        help='Deduplicate by command')
    parser.add_argument('--chronological',
                        '-r',
                        action='store_true',
                        help='Sort output chronologically')
    parser.add_argument('--exact',
                        '-w',
                        action='store_true',
                        help='Use exact match for command')
    parser.add_argument('--hostname',
                        '-H',
                        metavar='<like>',
                        help='Search by hostname. Use "." for localhost.')
    parser.add_argument(
        '--sync',
        metavar='<remote>',
        help='Sync with remote history. <remote> may be a hostname, a '
        'history database file, or <hostname>:<histfile>.')
    parser.add_argument('--histfile',
                        metavar='<filename>',
                        help='History file to use. Default: ' +
                        DEFAULT_HISTFILE)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument(
        '--import_hist',
        action="store_true",
        help='Import history from stdin in Unix timestamp + tab + cmd format'
        '(HISTTIMEFORMAT="%%s%%t" history | hist.py --import)')
    args = parser.parse_args(argv)
    if args.all:
        args.n = 0
    if args.session == '.':
        args.session = os.environ['HIST_SESSION_ID']
    if args.dir == '.':
        # Use logical $PWD from the shell, rather than physical one
        # from os.getcwd()
        args.dir = os.environ['PWD']
    if args.hostname == '.':
        args.hostname = socket.gethostname()
    return args


def create_table(conn):
    """
    Create the `hist` database table, but if it doesn't exist already.
    """
    cols = []
    for field in FIELDS[1:]:
        ftype = 'INTEGER' if field in INT_FIELDS else 'TEXT'
        cols.append('{} {} '.format(field, ftype))
    conn.execute(
        'CREATE TABLE IF NOT EXISTS hist (id TEXT PRIMARY KEY, {})'.format(
            ', '.join(cols)))
    conn.execute('CREATE INDEX IF NOT EXISTS ts_idx ON hist (timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS cmd_idx ON hist (cmd)')
    conn.execute('CREATE INDEX IF NOT EXISTS session_idx ON hist (session)')


def read_hist(fh):
    prev_idx = -1
    idx = 0
    cmd = ''
    timestamp = None
    for line in fh:
        m = re.match(r'\s*(\d+)\s+(\d+)\t(.*)', line)
        if m:
            idx = int(m.group(1))
            if idx == prev_idx + 1:
                if PY2:
                    cmd = cmd.decode('utf8')
                yield timestamp, cmd, prev_idx
            prev_idx = idx
            timestamp = int(m.group(2))
            cmd = m.group(3)
        else:
            cmd += "\n" + line.rstrip('\n')
    if idx > 0:
        if PY2:
            cmd = cmd.decode('utf8')
        yield timestamp, cmd, prev_idx


def insert_hist(conn, fh, session='', pwd='', elapsed=0, hostname='', status=0):
    for timestamp, cmd, idx in read_hist(fh):
        row = (session, pwd, timestamp, elapsed, cmd, hostname, status)
        row_str = b'\t'.join(str(f).encode('utf8') for f in row)
        rowid = hashlib.md5(row_str).hexdigest()[:16]
        conn.execute(INSERT, (rowid,) + row + (idx,))

def to_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def import_hist(conn, args):
    with conn:
        session = args.session or ''
        pwd = args.dir or ''
        hostname = args.hostname or ''
        elapsed = to_int(args.elapsed)
        status = to_int(args.status)
        create_table(conn)
        insert_hist(conn, sys.stdin, session, pwd, elapsed, hostname, status)


def parse_int_expr(expr):
    try:
        val = int(expr)
    except (TypeError, ValueError):
        pass
    else:
        return '==', val
    m = re.match(r'\s*(=|==|<|<=|>|>=|<>|!=)\s+(\d+)\s*$', expr)
    if m:
        return m.group(1), int(m.group(2))
    else:
        return None, None


def query(conn, args):
    select = 'SELECT {} FROM'.format(','.join(FIELDS))
    table = 'hist'
    wheres = []
    bindings = []
    if args.session:
        wheres.append('session LIKE ?')
        bindings.append(args.session)
    if args.dir:
        wheres.append('pwd LIKE ?')
        bindings.append(args.dir)
    if args.cmd:
        wheres.append('cmd LIKE ?')
        cmd = args.cmd if args.exact else '%{}%'.format(args.cmd)
        bindings.append(cmd)
    if args.hostname:
        wheres.append('hostname LIKE ?')
        bindings.append(args.hostname)
    if args.elapsed is not None:
        op, val = parse_int_expr(args.elapsed)
        if op:
            wheres.append('elapsed ' + op + ' ?')
            bindings.append(val)
    if args.status is not None:
        op, val = parse_int_expr(args.status)
        if op:
            wheres.append('status ' + op + ' ?')
            bindings.append(val)
    where = ''
    if wheres:
        where = 'WHERE ' + ' AND '.join(wheres)
    order = 'ORDER BY timestamp DESC, idx DESC'
    limit = 'LIMIT {}'.format(args.n) if args.n > 0 else ''
    group = 'GROUP BY cmd' if args.dedup else ''
    sql = ' '.join([select, table, where, group, order, limit])
    if args.chronological:
        sql = ' '.join([select, '(', sql, ')',
            'ORDER BY timestamp ASC, idx ASC'])
    #print(sql)
    for (rowid, session, pwd, timestamp_str, elapsed, cmd, hostname,
            status, idx) in conn.execute(sql, bindings):
        timestamp = datetime.datetime.fromtimestamp(int(timestamp_str))
        yield Entry(rowid ,session, pwd, timestamp, int(elapsed), cmd,
            hostname, status, idx)


def do_query(conn, args):
    formatter = HistFormatter(args.fmt, args.group)

    hist = query(conn, args)
    for entry in hist:
        for line in formatter.format(entry):
            print(line)


def send(fh, msg):
    json.dump(msg, fh)
    fh.write('\n')
    fh.flush()


def recv(fh):
    s = fh.readline()
    return json.loads(s)


def get_host_timestamps(conn):
    sql = 'SELECT hostname, MAX(timestamp) FROM hist GROUP BY hostname'
    with conn:
        return dict(conn.execute(sql))


def sync(conn, args):
    if ':' in args.sync:
        hostname, histfile = args.sync.split(':', 1)
    elif os.path.isfile(args.sync):
        histfile = args.sync
        hostname = None
    else:
        hostname = args.sync
        histfile = None
    cmd = ['hist.py', '--serve']
    if histfile:
        cmd += ['--histfile', histfile]
    if hostname:
        cmd = ['ssh', hostname] + cmd
    enc = {} if PY2 else {'encoding': 'utf8'}
    p = subprocess.Popen(cmd,
                         stdout=subprocess.PIPE,
                         stdin=subprocess.PIPE,
                         **enc)
    inp = p.stdout
    out = p.stdin

    msg = recv(inp)
    assert msg == 'READY'
    local_timestamps = get_host_timestamps(conn)
    print("Requesting entries newer than", local_timestamps, file=sys.stderr)

    send(out, ["PULL", local_timestamps])
    recv_entries(conn, inp)

    send(out, ["GET_TIMESTAMPS", None])
    remote_timestamps = recv(inp)
    print('Sending entries newer than', remote_timestamps, file=sys.stderr)
    send(out, ['PUSH', ''])
    send_entries(conn, out, remote_timestamps)

    send(out, ["BYE", {}])
    p.wait()
    inp.close()
    out.close()


def get_newer_entries(conn, timestamps):
    select = 'SELECT {} FROM hist'.format(','.join(FIELDS))
    wheres = []
    bindings = []
    for hostname, timestamp in timestamps.items():
        wheres.append('NOT (hostname == ? AND timestamp <= ?)')
        bindings += [hostname, timestamp]
    where = ''
    if wheres:
        where = 'WHERE ' + ' AND '.join(wheres)
    sql = ' '.join([select, where])
    for row in conn.execute(sql, bindings):
        yield row


def send_entries(conn, out, timestamps):
    send(out, 'BEGIN')
    for row in get_newer_entries(conn, timestamps):
        send(out, row)
    send(out, 'END')


def recv_entries(conn, inp):
    msg = recv(inp)
    assert msg == 'BEGIN'
    n = 0
    with conn:
        while True:
            msg = recv(inp)
            if msg == 'END':
                break
            n += 1
            conn.execute(INSERT, msg)
    print(n, 'rows transmitted', file=sys.stderr)


def serve(conn, args):
    out = sys.stdout
    inp = sys.stdin
    send(out, 'READY')
    while True:
        cmd, msg = recv(inp)
        if cmd == 'BYE':
            break
        elif cmd == 'PULL':
            send_entries(conn, out, msg)
        elif cmd == 'GET_TIMESTAMPS':
            timestamps = get_host_timestamps(conn)
            send(out, timestamps)
        elif cmd == 'PUSH':
            recv_entries(conn, inp)
        else:
            send(out, '?')


def quiet_handler(signum, frame):
    sys.exit()


def main():
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, quiet_handler)
    args = parse_args()
    histfile = args.histfile or os.path.expanduser(DEFAULT_HISTFILE)
    conn = sqlite3.connect(os.path.expanduser(histfile))

    if args.sync:
        action = sync
    elif args.serve:
        action = serve
    elif args.import_hist:
        action = import_hist
    else:
        action = do_query

    try:
        action(conn, args)
    except (KeyboardInterrupt):
        pass
    finally:
        conn.close()


if __name__ == '__main__':
    main()
