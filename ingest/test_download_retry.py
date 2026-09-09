import unittest
from unittest.mock import patch

from noaa_grib import read_url


class DownloadRetryTests(unittest.TestCase):
    @patch("noaa_grib.time.sleep")
    @patch("noaa_grib._read_url_once")
    def test_broken_connection_retried_with_same_range(self, download, sleep):
        download.side_effect = [BrokenPipeError("disconnected"), b"complete"]
        self.assertEqual(read_url("source", start=1, end=10), b"complete")
        self.assertEqual(download.call_count, 2)
        download.assert_called_with("source", start=1, end=10)
        sleep.assert_called_once_with(2)

    @patch("noaa_grib.time.sleep")
    @patch("noaa_grib._read_url_once", side_effect=ConnectionResetError)
    def test_connection_retries_are_bounded(self, download, sleep):
        with self.assertRaises(ConnectionResetError):
            read_url("source")
        self.assertEqual(download.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("noaa_grib.time.sleep")
    @patch("noaa_grib._read_url_once", side_effect=ValueError("invalid range"))
    def test_integrity_failure_not_retried(self, download, sleep):
        with self.assertRaises(ValueError):
            read_url("source")
        self.assertEqual(download.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
