import pytest

from app.source_quality import classify, label


class TestClassify:
    """Test source classification for one URL of each type."""

    def test_official_gov_pk(self):
        """.gov.pk domains should be official."""
        assert classify("https://example.gov.pk/report.pdf") == "official"

    def test_official_gov(self):
        """.gov domains should be official."""
        assert classify("https://example.gov/data") == "official"

    def test_official_int(self):
        """.int domains should be official."""
        assert classify("https://example.int/info") == "official"

    def test_official_org_pk(self):
        """.org.pk domains should be official."""
        assert classify("https://example.org.pk/data") == "official"

    def test_academic_edu(self):
        """.edu domains should be academic."""
        assert classify("https://harvard.edu/research.pdf") == "academic"

    def test_academic_sciencedirect(self):
        """sciencedirect.com should be academic."""
        assert classify("https://sciencedirect.com/science/article") == "academic"

    def test_academic_springer(self):
        """springer.com should be academic."""
        assert classify("https://springer.com/book") == "academic"

    def test_academic_mdpi(self):
        """mdpi.com should be academic."""
        assert classify("https://mdpi.com/journal") == "academic"

    def test_academic_researchgate(self):
        """researchgate.net should be academic."""
        assert classify("https://researchgate.net/publication") == "academic"

    def test_academic_academia(self):
        """academia.edu should be academic."""
        assert classify("https://academia.edu/profile") == "academic"

    def test_news_dawn(self):
        """dawn.com should be news."""
        assert classify("https://dawn.com/news") == "news"

    def test_news_tribune(self):
        """tribune.com.pk should be news."""
        assert classify("https://tribune.com.pk/national") == "news"

    def test_news_thenews(self):
        """thenews.com.pk should be news."""
        assert classify("https://thenews.com.pk/politics") == "news"

    def test_news_reuters(self):
        """reuters.com should be news."""
        assert classify("https://reuters.com/world") == "news"

    def test_news_bbc(self):
        """bbc.com should be news."""
        assert classify("https://bbc.com/world") == "news"

    def test_aggregator_marketresearchreports(self):
        """marketresearchreports.com should be aggregator."""
        assert classify("https://marketresearchreports.com/report") == "aggregator"

    def test_aggregator_market_us(self):
        """market.us should be aggregator."""
        assert classify("https://market.us/data") == "aggregator"

    def test_aggregator_marketsandmarkets(self):
        """marketsandmarkets.com should be aggregator."""
        assert classify("https://marketsandmarkets.com/report") == "aggregator"

    def test_aggregator_maximizemarketresearch(self):
        """maximizemarketresearch.com should be aggregator."""
        assert classify("https://maximizemarketresearch.com/report") == "aggregator"

    def test_aggregator_stellarmr(self):
        """stellarmr.com should be aggregator."""
        assert classify("https://stellarmr.com/insights") == "aggregator"

    def test_aggregator_6wresearch(self):
        """6wresearch.com should be aggregator."""
        assert classify("https://6wresearch.com/results") == "aggregator"

    def test_aggregator_marketdataforecast(self):
        """marketdataforecast.com should be aggregator."""
        assert classify("https://marketdataforecast.com/forecast") == "aggregator"

    def test_aggregator_statista(self):
        """statista.com should be aggregator."""
        assert classify("https://statista.com/statistics") == "aggregator"

    def test_company_com_pk(self):
        """A .com.pk domain not in other lists should be company."""
        assert classify("https://brandname.com.pk/products") == "company"

    def test_company_com(self):
        """A .com domain not in other lists should be company."""
        assert classify("https://brandname.com/about") == "company"

    def test_unknown(self):
        """An unrecognized domain should be unknown."""
        assert classify("https://example.random/invalid") == "unknown"


class TestLabel:
    """Test the human-readable label output."""

    def test_label_official(self):
        """official -> 'official'"""
        assert label("https://example.gov.pk/report.pdf") == "official"

    def test_label_academic(self):
        """academic -> 'academic'"""
        assert label("https://harvard.edu/research.pdf") == "academic"

    def test_label_news(self):
        """news -> 'news'"""
        assert label("https://dawn.com/news") == "news"

    def test_label_aggregator(self):
        """aggregator -> 'aggregator'"""
        assert label("https://marketresearchreports.com/report") == "aggregator"

    def test_label_company(self):
        """company -> 'company'"""
        assert label("https://brandname.com.pk/products") == "company"

    def test_label_unknown(self):
        """unknown -> 'unknown'"""
        assert label("https://example.random/invalid") == "unknown"