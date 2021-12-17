import unittest

import hist


class TestHist(unittest.TestCase):

    def test_read_hist(self):
        with open('htest') as fh:
            got = list(hist.read_hist(fh))
        expected = [
            (1639348558, 'cd hist'),
            (1639348560, 'man bash'),
            (1639350379, ''),
            (1639350393, 'echo 1'),
            (1639350393, 'echo "a\nb"'),
            (1639350393, 'echo 3'),
        ]
        self.assertEqual(got, expected)


if __name__ == '__main__':
    unittest.main()
