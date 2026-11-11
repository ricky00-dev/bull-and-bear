"""Opt-in extraction smoke test against a public Korean publisher article."""
import os

import pytest

from bullbear.news_extraction import ArticleExtractor


def test_live_korean_news_article():
    url = os.getenv("BULLBEAR_TEST_NEWS_URL")
    if not url:
        pytest.skip("set BULLBEAR_TEST_NEWS_URL to a public Korean publisher article")
    result = ArticleExtractor().fetch(url)
    assert result.status == "SUCCESS", f"{result.status}: {result.error_code} (network or publisher policy may vary)"
    assert any("가" <= char <= "힣" for char in result.content)
