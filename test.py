# coding=utf-8
import datetime
import sqlite3
import unittest

import hist


class TestHist(unittest.TestCase):

    def test_read_hist(self):
        with open('htest') as fh:
            got = list(hist.read_hist(fh))
        expected = [
            (1639348558, 'cd hist', 99964),
            (1639348560, 'man bash', 99965),
            (1639350379, '', 99966),
            (1639350393, u'echo 😸', 99967),
            (1639350393, 'echo "a\nb"', 99968),
            (1639350393, 'echo 3', 99969),
        ]
        self.assertEqual(got, expected)

    def test_insert_hist(self):
        conn = sqlite3.connect(':memory:')
        fh = ['99964  1639348558	cd hist\n']
        args = hist.parse_args([])
        with conn:
            hist.create_table(conn)
            hist.insert_hist(conn, fh)
        got = list(hist.query(conn, args))
        expected = [
            hist.Entry(id='d5562323aa17e468',
                       session='',
                       pwd='',
                       timestamp=datetime.datetime(2021, 12, 12, 17, 35, 58),
                       elapsed=0,
                       cmd='cd hist',
                       hostname='',
                       status=0,
                       idx=99964,)
        ]
        self.assertEqual(got, expected)


if __name__ == '__main__':
    unittest.main()
