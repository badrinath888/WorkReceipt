import unittest, urllib.request, urllib.error
from desktop import main as dm


class Shell(unittest.TestCase):
    def test_server_starts_serves_and_stops(self):
        srv, url = dm.start_server()
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertEqual(urllib.request.urlopen(url).status, 200)
        r = urllib.request.Request(url + "api/settings", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as c:   # no token => forbidden
            urllib.request.urlopen(r)
        self.assertEqual(c.exception.code, 403)
        dm.stop_server(srv)
        with self.assertRaises(Exception):
            urllib.request.urlopen(url, timeout=1)

    def test_reveal_rejects_unknown_paths(self):
        self.assertFalse(dm.Api().reveal("/etc/passwd"))


if __name__ == "__main__":
    unittest.main()
