def test_import_llmharvester():
    import llmharvester
    from llmharvester.config import HarvesterConfig
    from llmharvester.engine import Harvester
    assert Harvester is not None
    assert HarvesterConfig is not None


def test_compat_import_ztharvester():
    import ztharvester
    from ztharvester.config import HarvesterConfig
    from ztharvester.engine import Harvester
    assert Harvester is not None
    assert HarvesterConfig is not None


def test_browser_stop_and_flags():
    from llmharvester.browser import stop_cdp_browser, is_cdp_alive
    # Calling stop on non-existent port should be safe and return None
    stop_cdp_browser(port=19999, timeout=0.1)
    assert is_cdp_alive(port=19999, timeout=0.1) is None

