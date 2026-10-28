import unittest

from bitcoin_event_news import associate, timed_incident_returns


class NewsAssociationTests(unittest.TestCase):
    def setUp(self):
        self.events = [{"event_id": "E01", "peak_available_at_utc": "2020-03-13T02:45:00Z", "return_30m_pct": "33.6"}]
        self.catalog = {"sources": [{"source_id": "N01", "title": "Relatório posterior",
                                     "url": "https://example.org/report", "publication_date": "2020-03-16",
                                     "publication_precision": "day", "event_time_utc": "2020-03-13T02:16:00Z"}],
                        "associations": [{"event_id": "E01", "source_id": "N01",
                                          "association": "documented_incident_temporal_overlap"}]}

    def test_incident_time_is_separate_from_publication_and_not_causal(self):
        rows, events = associate(self.events, self.catalog)
        self.assertEqual(rows[0]["peak_minus_incident_minutes"], 29)
        self.assertEqual(rows[0]["publication_date"], "2020-03-16")
        self.assertEqual(rows[0]["published_at_utc"], "")
        self.assertFalse(rows[0]["ready_for_realtime_training"])
        self.assertFalse(events[0]["causality_identified"])

    def test_missing_source_is_rejected(self):
        self.catalog["associations"][0]["source_id"] = "missing"
        with self.assertRaises(ValueError):
            associate(self.events, self.catalog)

    def test_explicit_unresolved_event_preserves_unknown(self):
        self.catalog["associations"][0].update(source_id="", association="unresolved")
        rows, events = associate(self.events, self.catalog)
        self.assertEqual(rows[0]["source_url"], "")
        self.assertEqual(rows[0]["peak_minus_incident_minutes"], "")
        self.assertEqual(events[0]["research_status"], "reviewed_unresolved")

    def test_pre_post_returns_use_the_incident_anchor(self):
        links, _ = associate(self.events, self.catalog)
        context = [{"event_id": "E01", "available_at_utc": f"2020-03-13T02:{minute}:00Z", "close_usdt": price}
                   for minute, price in (("15", 90), ("16", 100), ("17", 110))]
        rows = timed_incident_returns(context, links)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["pre_return_pct"], 100/9)
        self.assertAlmostEqual(rows[0]["post_return_pct"], 10)


if __name__ == "__main__":
    unittest.main()
