from datetime import date, datetime, timedelta
import json
from pathlib import Path
import unittest

CATALOG = Path(__file__).parent / "research" / "bitcoin_news_sources.json"
DATE_FORMATS = {"day": r"\d{4}-\d{2}-\d{2}", "minute_of_update": r"\d{4}-\d{2}-\d{2}",
                "month": r"\d{4}-\d{2}", "unknown": r""}


class NewsCatalogTests(unittest.TestCase):
    """Integridade do catálogo documental versionado; não avalia o conteúdo das fontes."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_sources_have_unique_ids_and_https_urls(self):
        ids = [source["source_id"] for source in self.catalog["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        for source in self.catalog["sources"]:
            with self.subTest(source=source["source_id"]):
                self.assertTrue(source["url"].startswith("https://"))
                self.assertTrue(source["title"] and source["publisher"] and source["source_type"])

    def test_dates_match_declared_precision(self):
        for source in self.catalog["sources"]:
            with self.subTest(source=source["source_id"]):
                pattern = DATE_FORMATS[source["publication_precision"]]
                self.assertRegex(source["publication_date"], f"^{pattern}$")
                if source["event_date"]:
                    date.fromisoformat(source["event_date"])
                for key in ("published_at_utc", "event_time_utc"):
                    if source[key]:
                        parsed = datetime.fromisoformat(source[key])
                        self.assertEqual(parsed.utcoffset(), timedelta(0))
                self.assertEqual(bool(source["published_at_utc"]), source["publication_precision"] == "minute_of_update")

    def test_associations_reference_known_sources(self):
        ids = {source["source_id"] for source in self.catalog["sources"]}
        for link in self.catalog["associations"]:
            with self.subTest(link=link):
                self.assertRegex(link["event_id"], r"^E\d{2}$")
                self.assertTrue(link["assessment"])
                if link["association"] == "unresolved":
                    self.assertEqual(link["source_id"], "")
                else:
                    self.assertIn(link["source_id"], ids)
                if link["association"] == "documented_incident_temporal_overlap":
                    source = next(s for s in self.catalog["sources"] if s["source_id"] == link["source_id"])
                    self.assertTrue(source["event_time_utc"], "Sobreposição temporal exige horário do incidente")


if __name__ == "__main__":
    unittest.main()
