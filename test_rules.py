"""Checks for the rules engine and the config loader.   Run:  python -m unittest test_rules -v"""

import os
import shutil
import tempfile
import time
import unittest

import config
import rules


class Conditions(unittest.TestCase):
    V = {"total": 12400.0, "claimed": 12400.0, "other": 99.0, "vendor": "Acme Ltd", "missing_one": None,
         "sender": "finance@acme.com", "text": "Total due: Rs 12,400.00 Please pay by 30 Oct", "invoice_no": "0412"}

    def check(self, cond, expected):
        self.assertEqual(rules.evaluate_condition(cond, self.V), expected, cond)

    def test_numbers(self):
        for cond, exp in [("total > 50000", False), ("total > 10000", True), ("total >= 12400", True),
                          ("total < 12400", False), ("total <= 12400", True), ("total == 12,400", True),
                          ("total != 12400", False), ("total>10000", True)]:
            self.check(cond, exp)

    def test_compare_two_fields(self):
        self.check("total == claimed", True)
        self.check("total != claimed", False)
        self.check("total != other", True)
        self.check("total > other", True)

    def test_text(self):
        for cond, exp in [("vendor == acme ltd", True), ("vendor == 'Acme Ltd'", True), ("vendor contains acme", True),
                          ("vendor not contains globex", True), ("vendor matches ^acme", True),
                          ("vendor not matches ^globex", True), ("text contains 'rs 12,400'", True),
                          ("text contains refund", False)]:
            self.check(cond, exp)

    def test_in_lists(self):
        self.check("sender in finance@acme.com, billing@globex.com", True)
        self.check("sender not in finance@acme.com, billing@globex.com", False)
        self.check("sender not in someone@else.com", True)
        self.check("vendor in 'Acme Ltd', Globex", True)

    def test_exists_and_missing(self):
        self.check("total exists", True)
        self.check("missing_one exists", False)
        self.check("missing_one missing", True)
        self.check("total missing", False)

    def test_missing_value_makes_a_line_false(self):
        for cond in ["missing_one > 5", "missing_one == 5", "missing_one != 5", "missing_one contains x",
                     "missing_one not contains x", "total != missing_one", "total > missing_one"]:
            self.check(cond, False)

    def test_text_that_looks_like_a_number_stays_text(self):
        self.check("invoice_no == 0412", True)
        self.check("invoice_no == 'abc'", False)

    def test_bad_lines(self):
        for bad in ["total", "total >", "total exists now", "> 5", "total ~ 5"]:
            with self.assertRaises(ValueError, msg=bad):
                rules.parse_condition(bad)


class Fields(unittest.TestCase):
    def test_numbers_and_currency(self):
        for raw, exp in [("12,400.50", 12400.5), ("Rs. 12,400", 12400.0), ("₹ 1,24,000.00", 124000.0),
                         ("-5", -5.0), ("abc", None), ("", None), (None, None)]:
            self.assertEqual(rules.to_number(raw), exp, raw)

    def test_extract_first_and_last(self):
        text = "Sub Total: 11,000.00\nTotal due: Rs 12,400.00"
        spec = {"pattern": r"total[^\d]*(\d[\d,]*(?:\.\d+)?)", "type": "number"}
        self.assertEqual(rules.extract_value(spec, text), 11000.0)
        self.assertEqual(rules.extract_value(dict(spec, match="last"), text), 12400.0)

    def test_not_found(self):
        self.assertIsNone(rules.extract_value({"pattern": r"po\s*(\d+)"}, "nothing here"))

    def test_default_fields_on_a_typical_invoice(self):
        cfg = config.load()["fields"]
        text = "INVOICE\nInvoice No. 2026-0412\nSubtotal: 11,000.00\nTotal due: Rs 12,400.00"
        got = rules.extract_doc_fields(cfg, text)
        self.assertEqual(got, {"invoice_no": "2026-0412", "invoice_total": 12400.0})
        mail = {"subject": "Invoice", "body": "Hi, the total amount is Rs 12,400 as agreed."}
        self.assertEqual(rules.extract_mail_fields(cfg, mail), {"claimed_total": 12400.0})


class Effects(unittest.TestCase):
    RULES = [
        {"name": "big", "when": ["total > 100"], "reply": "note one", "flag": "big amount"},
        {"name": "off", "enabled": False, "when": ["total > 1"], "reply": "never"},
        {"name": "mismatch", "when": ["total != claimed"], "mode": "replace", "reply": "REPLACED"},
        {"name": "second replace", "when": ["total > 1"], "mode": "replace", "reply": "IGNORED"},
        {"name": "recat", "when": ["total > 1"], "category": "NEEDS_HUMAN"},
        {"name": "quiet", "when": ["sender == nobody@x.com"], "no_reply": True},
    ]

    def test_effects(self):
        fx = rules.apply_rules(self.RULES, {"total": 500.0, "claimed": 400.0, "sender": "a@b.com"})
        self.assertEqual(fx.notes, ["note one"])
        self.assertEqual(fx.replace, "REPLACED")            # first replace wins
        self.assertEqual(fx.category, "NEEDS_HUMAN")
        self.assertEqual(fx.flags, ["big amount"])
        self.assertFalse(fx.no_reply)
        self.assertNotIn("off", fx.matched)

    def test_nothing_fires(self):
        fx = rules.apply_rules(self.RULES, {"total": 1.0, "claimed": 1.0, "sender": "a@b.com"})
        self.assertEqual(fx.matched, [])


class ConfigChecks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        shutil.copy(config.CONFIG_PATH, self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def edit(self, old, new):
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(old, text)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))

    def error_text(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.load(self.path)
        return str(cm.exception)

    def test_default_file_is_valid(self):
        config.load(self.path)

    def test_typo_in_a_placeholder(self):
        self.edit("Reference: {references}\n      Files: {files}", "Reference: {referenses}\n      Files: {files}")
        self.assertIn("{referenses}", self.error_text())

    def test_typo_in_a_setting(self):
        self.edit("max_file_mb: 20", "max_file_mbs: 20")
        self.assertIn("max_file_mbs", self.error_text())

    def test_bad_regex(self):
        self.edit(r"pattern: 'invoice\s*(?:no", r"pattern: 'invoice\s*((?:no")
        self.assertIn("regular expression", self.error_text())

    def test_unknown_name_in_a_rule(self):
        self.edit("- invoice_total > 50000", "- invoice_totl > 50000")
        self.assertIn("invoice_totl", self.error_text())

    def test_unbalanced_brackets(self):
        self.edit("Reference: {references}\n      Files:", "Reference: {references\n      Files:")
        self.assertIn("balanced", self.error_text())

    def test_reload_keeps_the_old_config_when_the_new_one_is_broken(self):
        config.CONFIG_PATH = self.path
        try:
            config.load()
            self.assertEqual(config.setting("max_file_mb"), 20)
            self.edit("max_file_mb: 20", "max_file_mb: 5")
            os.utime(self.path, (time.time() + 5, time.time() + 5))
            self.assertTrue(config.reload_if_changed())
            self.assertEqual(config.setting("max_file_mb"), 5)

            self.edit("max_file_mb: 5", "max_file_mbs: 5")          # now break it
            os.utime(self.path, (time.time() + 10, time.time() + 10))
            self.assertFalse(config.reload_if_changed())
            self.assertEqual(config.setting("max_file_mb"), 5)       # still the last good version
        finally:
            config.CONFIG_PATH = os.environ.get("INGEST_CONFIG", os.path.join(config.BASE_DIR, "config.yaml"))
            config.load()


if __name__ == "__main__":
    unittest.main()
