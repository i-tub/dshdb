import argparse
import socket
import sqlite3
import os


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--insert', nargs=5)
    return parser.parse_args()


INSERT = """INSERT INTO hist
            (session, pwd, timestamp, elapsed, cmd, hostname)
            VALUES (?,?,?,?,?,?)"""


def main():
    args = parse_args()
    hostname = socket.gethostname()
    if args.insert:
        conn = sqlite3.connect(os.path.expanduser('~/.hist.db'))
        with conn:
            conn.execute(INSERT, args.insert + [hostname])
        conn.close()


if __name__ == '__main__':
    main()
