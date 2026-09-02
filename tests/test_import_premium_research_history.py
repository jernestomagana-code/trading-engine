import json
import tempfile
import unittest
from pathlib import Path

from scripts import import_premium_research_history as importer


class ImportPremiumResearchHistoryTests(unittest.TestCase):
    def test_json_records_container_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps({"records": [{"ticker": "SPY"}]}))
            self.assertEqual(importer.load_records(path), [{"ticker": "SPY"}])

    def test_csv_is_supported_without_guessing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            path.write_text("ticker,close\nSPY,700\n")
            self.assertEqual(importer.load_records(path)[0]["close"], "700")


if __name__ == "__main__":
    unittest.main()
