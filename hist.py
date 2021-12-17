#!/bin/env python

from __future__ import print_function

import argparse
import collections
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import datetime as dt

DEFAULT_HISTFILE = '~/.hist.db'
FIELDS = 'session, pwd, timestamp, elapsed, cmd, hostname'

Entry = collections.namedtuple('Entry', FIELDS)


class Printer:

    def __init__(self, full, group):
        self.prev_date = None
        self.full = full
        self.group = group

    def print(self, entry):
        ts = entry.timestamp
        date = ts.date().isoformat()
        if date != self.prev_date:
            self.prev_date = date
            if self.group:
                print('{}:'.format(date))
        if self.group:
            ts = ts.time()
        if self.full:
            fields = [
                ts.isoformat(), entry.hostname, entry.session, entry.pwd,
                entry.elapsed, entry.cmd
            ]
        else:
            fields = [ts.isoformat(), entry.cmd]
        if self.group:
            fields.insert(0, '')
        if sys.version_info[0] < 3:
            s = '\t'.join(map(unicode, fields))
            print(s.encode('utf8'))
        else:
            print('\t'.join(map(str, fields)))


def parse_args():
    parser = argparse.ArgumentParser()
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
    parser.add_argument('--cmd',
                        '-c',
                        metavar='<like>',
                        help='Search by command.')
    parser.add_argument(
        '--full',
        '-f',
        action='store_true',
        help='Full output, including session ID, PWD, and elapsed time.')
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
    parser.add_argument('--hostname', '-H',
        metavar='<like>',
        help='Search by hostname. Use "." for localhost.')
    parser.add_argument('--sync',
                        metavar='<remote>',
                        help='Sync with remote history.')
    parser.add_argument('--histfile',
                        metavar='<filename>',
                        help='History file to use. Default: '
                        + DEFAULT_HISTFILE)
    parser.add_argument('--serve',
                        action='store_true',
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.all:
        args.n = 0
    return args


def query(conn, args):
    select = 'SELECT {} FROM'.format(FIELDS)
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
    where = ''
    if wheres:
        where = 'WHERE ' + ' AND '.join(wheres)
    order = 'ORDER BY timestamp DESC'
    limit = 'LIMIT {}'.format(args.n) if args.n > 0 else ''
    group = 'GROUP BY cmd' if args.dedup else ''
    sql = ' '.join([select, table, where, group, order, limit])
    #print(sql)
    if args.chronological:
        sql = ' '.join([select, '(', sql, ')', 'ORDER BY timestamp ASC'])
    for session, pwd, timestamp_str, elapsed, cmd, hostname in conn.execute(
            sql, bindings):
        timestamp = dt.datetime.fromtimestamp(int(timestamp_str))
        yield Entry(session, pwd, timestamp, int(elapsed), cmd, hostname)


def do_query(conn, args):
    if args.session == '.':
        args.session = os.environ['HIST_SESSION_ID']
    if args.dir == '.':
        args.dir = os.getcwd()
    if args.hostname == '.':
        args.hostname = socket.gethostname()
    printer = Printer(args.full, args.group)

    hist = query(conn, args)
    for entry in hist:
        printer.print(entry)

def send(fh, msg):
    json.dump(msg, fh);
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
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
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
    

def get_newer_entries(conn, timestamps):
    select = 'SELECT {} FROM hist'.format(FIELDS)
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
    qs = ','.join(['?'] * len(FIELDS.split()))
    sql = 'INSERT INTO hist ({}) VALUES ({})'.format(FIELDS, qs)
    with conn:
        while True:
            msg = recv(inp)
            if msg == 'END':
                break
            n += 1
            conn.execute(sql, msg)
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
