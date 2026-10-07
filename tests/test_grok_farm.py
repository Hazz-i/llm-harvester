import unittest
from unittest.mock import patch
from llmharvester.grok_farm import select_working_residential_proxy, check_proxy_connect

class TestGrokFarmProxy(unittest.TestCase):
    def test_select_empty_candidates(self):
        self.assertIsNone(select_working_residential_proxy([]))

    @patch("random.shuffle", lambda x: None)
    @patch("llmharvester.grok_farm.check_proxy_connect")
    def test_select_first_working_proxy(self, mock_check):
        mock_check.side_effect = [False, True]
        candidates = [
            "http://dead:pass@1.1.1.1:8080",
            "http://alive:pass@2.2.2.2:8080"
        ]
        chosen = select_working_residential_proxy(candidates, max_tries=2)
        self.assertEqual(chosen, "http://alive:pass@2.2.2.2:8080")

    @patch("llmharvester.grok_farm.check_proxy_connect")
    def test_select_all_dead(self, mock_check):
        mock_check.return_value = False
        candidates = ["http://dead:pass@1.1.1.1:8080"]
        chosen = select_working_residential_proxy(candidates, max_tries=1)
        self.assertIsNone(chosen)

if __name__ == "__main__":
    unittest.main()
