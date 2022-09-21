#!/bin/env python3
"""
Search or manipulate the Distributed Shell History Database.

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

DEFAULT_HISTFILE = os.path.join(os.environ.get('HIST_DIR', '~/.hist'),
                                'hist.db')

FIELDS = [
    'id', 'session', 'pwd', 'timestamp', 'elapsed', 'cmd', 'hostname', 'status',
    'idx'
]
# Fields are TEXT unless listed below.
INT_FIELDS = {'timestamp', 'elapsed', 'status', 'idx'}

Entry = collections.namedtuple('Entry', FIELDS)

# For use in --fmt argument.
COLS = {
    'c': 'cmd',
    'd': '~pwd',
    'D': 'pwd',
    'e': 'elapsed',
    'h': 'hostname',
    'i': 'id',
    's': 'session',
    't': 'timestamp',
    'x': 'status',
}
DEFAULT_FMT = 'thsdec'

TABLE_NAME = 'hist'

INSERT = 'INSERT OR IGNORE INTO {} ({}) VALUES ({})'.format(
    TABLE_NAME, ','.join(FIELDS), ','.join(['?'] * len(FIELDS)))

HOME = os.path.expanduser('~')

PY2 = sys.version_info.major < 3


class HistFormatter:
    """
    Stateful history output formatter. Remembers the date of the last command
    that was printed, to enable grouping the output by date.
    """

    def __init__(self, fmt, group=False):
        """
        :param fmt: string describing which columns to format. See `COLS` module
                    variable for valid fields.
        :param group: if true, output each date only once, only output the time
                      in each timestamp, and indent each non-date row.
        """
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
        """
        Format an Entry. The output may span multiple lines, which are yielded
        separately.

        :yield: lines to print (newline not included).
        """
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
    Opposite of os.path.expanduser() (e.g., turn /home/$USER/test into ~/test).
    """
    if dirname.startswith(HOME):
        return '~' + dirname[len(HOME):]
    else:
        return dirname


def create_table(conn):
    """
    Create the database table, but if it doesn't exist already.
    """
    cols = []
    for field in FIELDS[1:]:
        ftype = 'INTEGER' if field in INT_FIELDS else 'TEXT'
        cols.append('{} {} '.format(field, ftype))
    conn.execute(
        'CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, {})'.format(
            TABLE_NAME, ', '.join(cols)))
    conn.execute(
        'CREATE INDEX IF NOT EXISTS {0}_ts_idx ON {0} (timestamp DESC)'.format(
            TABLE_NAME))
    conn.execute('CREATE INDEX IF NOT EXISTS {0}_cmd_idx ON {0} (cmd)'.format(
        TABLE_NAME))
    conn.execute(
        'CREATE INDEX IF NOT EXISTS {0}_session_idx ON {0} (session)'.format(
            TABLE_NAME))


def parse_bash_history(fh):
    """
    Generator that parses the output of `HISTTIMEFORMAT="%s%t" history`.

    :yield: (timestamp, cmd, idx) as (int, str, int) tuples.
    """
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
                if cmd:
                    yield timestamp, cmd, prev_idx
            prev_idx = idx
            timestamp = int(m.group(2))
            cmd = m.group(3)
        else:
            cmd += "\n" + line.rstrip('\n')
    if idx > 0:
        if PY2:
            cmd = cmd.decode('utf8')
        if cmd:
            yield timestamp, cmd, prev_idx


def insert_hist(conn, fh, session='', pwd='', elapsed=0, hostname='', status=0):
    """
    Insert history from a file-like object. The input should be formatted like
    the output of `HISTTIMEFORMAT="%s%t" history`, which provides timestamp,
    command, and index; the rest of the fields are provided by the keyword
    arguments and will apply to every entry being inserted.

    Note that entries already in the database (as defined by all the fields
    other than idx, which is volatile) won't be inserted again. (Bug: because of
    this, two commands run within the same second on the same directory,
    hostname, shell session, with the same elapsed time and exit status, will be
    inserted into the database only once.)
    """
    for timestamp, cmd, idx in parse_bash_history(fh):
        row = (session, pwd, timestamp, elapsed, cmd, hostname, status)
        row_str = b'\t'.join(str(f).encode('utf8') for f in row)
        rowid = hashlib.md5(row_str).hexdigest()[:16]
        conn.execute(INSERT, (rowid,) + row + (idx,))


def to_int(s):
    """
    Convert string to int, or 0 if invalid.
    """
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def import_hist(conn, args):
    """
    Import history from stdin. The input should be formatted like the output of
    `HISTTIMEFORMAT="%s%t" history`, which provides timestamp, command, and
    index; the rest of the fields come from command-line arguments and apply to
    every entry being inserted.

    See insert_hist for more information.
    """
    with conn:
        session = args.session or ''
        pwd = args.dir or ''
        hostname = args.hostname or ''
        elapsed = to_int(args.elapsed)
        status = to_int(args.status)
        create_table(conn)
        insert_hist(conn, sys.stdin, session, pwd, elapsed, hostname, status)


def get_int_comparison_term(args, name):
    """
    Return an SQL WHERE term for the named argument.

    :param str name: name of db column / command-line arg

    :return: (sql_term, value).
    :rtype: (str, int)

    :raises: ValueError if invalid
    """
    expr = getattr(args, name)
    try:
        val = int(expr)
    except (TypeError, ValueError):
        pass  # Will parse string below
    else:
        return '{} == ?'.format(name), val
    m = re.match(r'\s*(=|==|<|<=|>|>=|<>|!=)\s+(\d+)\s*$', expr)
    if m:
        return '{} {} ?'.format(name, m.group(1)), int(m.group(2))
    else:
        raise ValueError("Invalid int expression" + expr)


def get_str_comparison_term(args, db_name, arg_name=None):
    """
    Return an SQL WHERE term for the named argument.

    :param str db_name: database column name
    :param str arg_name: command-line argument name

    :return: (sql_term, value).
    :rtype: (str, str)
    """
    arg_name = arg_name or db_name
    val = getattr(args, arg_name)
    eq = getattr(args, '_eq_' + arg_name, False)
    if eq or args.eq:
        op = '=='
        wildcard = ''
    elif args.like:
        op = 'LIKE'
        wildcard = '%'
    elif args.regex:
        op = 'REGEXP'
        wildcard = '.*'
    else:
        op = 'glob'
        wildcard = '*'
    where = ('{} {} ?'.format(db_name, op))
    val = val if args.exact else '{1}{0}{1}'.format(val, wildcard)
    if args.regex:
        val += '$'
    return (where, val)


def query(conn, args):
    """
    Query the database using the given command-line arguments and yield the
    matching entries.

    :return: generator of Entry.
    """
    select = 'SELECT {} FROM'.format(','.join(FIELDS))
    wheretups = []
    if args.session:
        wheretups.append(get_str_comparison_term(args, 'session'))
    if args.dir:
        wheretups.append(get_str_comparison_term(args, 'pwd', 'dir'))
    if args.cmd:
        wheretups.append(get_str_comparison_term(args, 'cmd'))
    if args.hostname:
        wheretups.append(get_str_comparison_term(args, 'hostname'))
    if args.elapsed is not None:
        wheretups.append(get_int_comparison_term(args, 'elapsed'))
    if args.status is not None:
        wheretups.append(get_int_comparison_term(args, 'status'))
    where = ''
    if wheretups:
        wheres, bindings = zip(*wheretups)
        where = 'WHERE ' + ' AND '.join(wheres)
    else:
        bindings = []
    order = 'ORDER BY timestamp DESC, idx DESC'
    limit = 'LIMIT {}'.format(args.n) if args.n > 0 else ''
    group = 'GROUP BY cmd' if args.dedup else ''
    sql = ' '.join([select, TABLE_NAME, where, group, order, limit])
    if args.chronological:
        sql = ' '.join(
            [select, '(', sql, ')', 'ORDER BY timestamp ASC, idx ASC'])

    for (rowid, session, pwd, timestamp_str, elapsed, cmd, hostname, status,
         idx) in conn.execute(sql, bindings):
        timestamp = datetime.datetime.fromtimestamp(int(timestamp_str))
        yield Entry(rowid, session, pwd, timestamp, int(elapsed), cmd, hostname,
                    status, idx)


def query_and_print(conn, args):
    """
    Query the database and print out the results.
    """
    formatter = HistFormatter(args.fmt, args.group)

    hist = query(conn, args)
    for entry in hist:
        for line in formatter.format(entry):
            print(line)


def send(fh, msg):
    """
    Send a JSON-encoded message to the given file object.
    """
    json.dump(msg, fh)
    fh.write('\n')
    fh.flush()


def recv(fh):
    """
    Receive a JSON-encoded message from the given file object.
    """
    s = fh.readline()
    return json.loads(s)


def get_host_timestamps(conn):
    """
    Get a dictionary with the most recent timestamp for each host in the
    database.

    :return: {hostname: timestamp}
    :rtype: {str: int}
    """
    sql = 'SELECT hostname, MAX(timestamp) FROM {} GROUP BY hostname'.format(
        TABLE_NAME)
    with conn:
        return dict(conn.execute(sql))


def sync(conn, args):
    """
    Synchronize the local database with a remote database. This is a two-step
    process:
    1) Fetch from the remote database all the entries that are newer than the
       newest entry we have for each hostname.
    2) Push to the remote database all the entries that are newer than the
       newest entry that the remote database has for each hostname.
    """
    # Parse args.sync argument to decide if it's a remote host or not.
    if ':' in args.sync:
        hostname, histfile = args.sync.split(':', 1)
    elif os.path.isfile(args.sync):
        histfile = args.sync
        hostname = None
    else:
        hostname = args.sync
        histfile = None

    # Start subprocess to connect to server process.
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

    # Start the dialog with the server process.
    msg = recv(inp)
    assert msg == 'READY'

    # 1) Get new entries from remote.
    local_timestamps = get_host_timestamps(conn)
    print("Requesting entries newer than", local_timestamps, file=sys.stderr)
    send(out, ["PULL", local_timestamps])
    recv_entries(conn, inp)

    # 2) Send new entries to remote.
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
    """
    Generator of entries for each host that are newer than the timestamp
    specified in the timestamps dict (if a host is not in the dict, all of its
    entries are yielded).

    :param timestamps: {hostname: timestamp}
    :type timestamp: {str: int}

    :yield: newer history entry tuples for insertion into database
    """
    select = 'SELECT {} FROM {}'.format(','.join(FIELDS), TABLE_NAME)
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
    """
    Send a list of entries sandwiched between a BEGIN message and
    an END message. Each row is a tuple with the values to insert.
    """
    send(out, 'BEGIN')
    for row in get_newer_entries(conn, timestamps):
        send(out, row)
    send(out, 'END')


def recv_entries(conn, inp):
    """
    Receive a list of entries sandwiched between a BEGIN message and
    an END message. Each row is a tuple with the values to insert.
    """
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
    """
    Act as the server for syncrhonization purposes. Receive requests from
    stdin and respond on stdout.
    """
    out = sys.stdout
    inp = sys.stdin
    send(out, 'READY')
    while True:
        # Requests must be a (command, message) pair.
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
            # Reply in the great ed tradition.
            send(out, '?')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    query_group = parser.add_argument_group(
        'query options',
        'In queries, <query> is normally interpreted as a glob, but it may\n'
        'be interpreted as an SQL LIKE, a Python regex, or a simple string\n'
        'by using one of the "query control options" below.')
    query_group.add_argument(
        'cmd',
        nargs='?',
        metavar='<cmd>',
        help='Search by command. This is a substring search, unless the '
        '--exact flag is used.')
    query_group.add_argument(
        '--session',
        '-s',
        metavar='<query>',
        help='Search by session ID. Use "." for current session.')
    query_group.add_argument(
        '--dir',
        '-d',
        metavar='<query>',
        help='Search by directory. Use "." for current working directory.')
    query_group.add_argument(
        '--elapsed',
        '-e',
        metavar='<int>|<op><int>',
        help='Elapsed time. May use a string with an operator (e.g., "> 10")')
    query_group.add_argument(
        '--status',
        '-x',
        metavar='<int>|<op><int>',
        help='Exit status. May use a string with an operator (e.g., "!= 0")')
    query_group.add_argument('--hostname',
                             '-H',
                             metavar='<query>',
                             help='Search by hostname. Use "." for localhost.')

    query_ctrl_group = parser.add_argument_group('query control options')
    query_op = query_ctrl_group.add_mutually_exclusive_group()
    query_op.add_argument(
        '--regex',
        '-R',
        action='store_true',
        help='Use Pyton regular expressions for matching command.')
    query_op.add_argument('--like',
                          '-L',
                          action='store_true',
                          help='Use SQL LIKE for matching command.')
    query_op.add_argument('--eq',
                          '-E',
                          action='store_true',
                          help='Use SQL == for matching command.')
    query_ctrl_group.add_argument(
        '--exact',
        '-w',
        action='store_true',
        help='Use "exact" match for command (don\'t surround it with '
        ' wildcards implicitly for GLOB/LIKE/REGEXP comparisons; '
        ' but wildcards in <cmd> are still magical).')

    fmt_group = parser.add_argument_group('output control')
    fmt_group.add_argument('--all',
                           '-a',
                           action='store_true',
                           help='Return all results.')
    fmt_group.add_argument(
        '-n',
        type=int,
        metavar='<int>',
        default=30,
        help='Number of results to return. Default=%(default)s.')
    fmt_group.add_argument(
        '--fmt',
        '-f',
        metavar='<fields>',
        default='tc',
        help='Format spec; a string of one-character field identifiers: '
        'c=command, d=directory (home abbreviated ~), D=directory, e=elapsed, '
        'h=hostname, i=id, s=session, t=timestamp, x=exit status. '
        'Default is "%(default)s". '
        'Use empty string for "{}".'.format(DEFAULT_FMT))
    fmt_group.add_argument('--group',
                           '-g',
                           action='store_true',
                           help='Group results by date.')
    fmt_group.add_argument('--dedup',
                           '-u',
                           action='store_true',
                           help='Deduplicate by command.')
    fmt_group.add_argument('--chronological',
                           '-r',
                           action='store_true',
                           help='Sort output chronologically')

    other_group = parser.add_argument_group('other options')
    other_group.add_argument('--histfile',
                             metavar='<filename>',
                             help='History file to use. Default: ' +
                             DEFAULT_HISTFILE)
    excl_group = other_group.add_mutually_exclusive_group()
    excl_group.add_argument(
        '--sync',
        metavar='<remote>',
        help='Sync with remote history. <remote> may be a hostname, a '
        'history database file, or <hostname>:<histfile>. For remote '
        'hosts, ssh is used and hist.py must be installed on the remote host.')
    excl_group.add_argument('--serve',
                            action='store_true',
                            help=argparse.SUPPRESS)
    excl_group.add_argument(
        '--import_hist',
        action="store_true",
        help='Import history from stdin in Unix timestamp + tab + cmd format '
        '(i.e., HISTTIMEFORMAT="%%s%%t" history | hist.py --import). '
        'The `history` output only provides timestamp and command; other '
        'metadata may be supplied with --dir, --elapsed, --session, '
        '--hostname, and --status, but will apply to every row imported.')

    args = parser.parse_args(argv)
    args._eq_dir = args._eq_session = args._eq_hostname = False
    if args.all:
        args.n = 0
    if args.session == '.':
        args.session = os.environ['HIST_SESSION_ID']
        args._eq_session = True
    if args.dir == '.':
        # Use logical $PWD from the shell, rather than physical one
        # from os.getcwd()
        args.dir = os.environ['PWD']
        args._eq_dir = True
    if args.hostname == '.':
        args.hostname = socket.gethostname()
        args._eq_hostname = True
    return args


def quiet_handler(signum, frame):
    """
    Signal handler for exiting quietly.
    """
    sys.exit()


def main():
    if hasattr(signal, "SIGPIPE"):
        # Disable SIGPIPE handler so we don't get a traceback if the output
        # is typed to something like `head`.
        signal.signal(signal.SIGPIPE, quiet_handler)

    args = parse_args()
    histfile = args.histfile or os.path.expanduser(DEFAULT_HISTFILE)

    os.umask(0x077)  # Make sure database file is created private.
    conn = sqlite3.connect(os.path.expanduser(histfile))
    conn.create_function('REGEXP', 2, lambda r, s: bool(re.match(r, s)))

    if args.sync:
        action = sync
    elif args.serve:
        action = serve
    elif args.import_hist:
        action = import_hist
    else:
        action = query_and_print

    try:
        action(conn, args)
    except (KeyboardInterrupt):
        pass
    finally:
        conn.close()


if __name__ == '__main__':
    main()
