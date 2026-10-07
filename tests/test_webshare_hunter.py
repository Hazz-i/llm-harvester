import unittest
from unittest.mock import patch, MagicMock
from llmharvester.webshare_hunter import check_capsolver_balance, find_grok_proxies_txt
from llmharvester.grok_farm import MailTmService, DuckMailService

class TestWebshareHunter(unittest.TestCase):
    def test_check_capsolver_balance_no_key(self):
        res = check_capsolver_balance(api_key="")
        self.assertFalse(res["has_key"])
        self.assertFalse(res["can_headless"])
        self.assertEqual(res["status"], "NOT_CONFIGURED")

    def test_mail_tm_service_alias(self):
        self.assertIs(DuckMailService, MailTmService)
        service = MailTmService()
        self.assertIn("https://api.mail.tm", service.api_bases)
        self.assertIn("https://api.mail.gw", service.api_bases)

    def test_find_grok_proxies_txt(self):
        path = find_grok_proxies_txt()
        self.assertTrue(path.endswith("proxies.txt"))

    def test_append_to_proxies_txt(self):
        import tempfile, os
        from llmharvester.webshare_hunter import append_to_proxies_txt
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test_proxies.txt")
            proxies = ["http://u:p@1.1.1.1:8080", "http://u:p@2.2.2.2:8080"]
            added = append_to_proxies_txt(proxies, filepath=fpath)
            self.assertEqual(added, 2)
            # Duplicate addition should be 0
            added_dup = append_to_proxies_txt(proxies, filepath=fpath)
            self.assertEqual(added_dup, 0)

    def test_sync_to_9router(self):
        import tempfile, sqlite3, os
        from llmharvester.webshare_hunter import sync_to_9router
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.sqlite")
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("CREATE TABLE proxyPools (id TEXT PRIMARY KEY, isActive INTEGER, testStatus TEXT, data TEXT, createdAt TEXT, updatedAt TEXT)")
            conn.commit()
            conn.close()

            proxies = ["http://user:pass@127.0.0.1:8080"]
            added = sync_to_9router(proxies, db_path=db_path)
            self.assertEqual(added, 1)

if __name__ == "__main__":
    unittest.main()
