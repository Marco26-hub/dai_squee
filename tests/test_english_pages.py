from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
import json
import unittest
from scripts.build_english import PAGES

ROOT = Path(__file__).resolve().parents[1]

class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags=[]
        self.feed(source)
    def handle_starttag(self,tag,attrs):
        self.tags.append((tag,dict(attrs)))

class EnglishPagesTest(unittest.TestCase):
    def test_all_translated_pages_and_local_links(self):
        for filename in PAGES.values():
            path=ROOT/"en"/filename
            source=path.read_text()
            page=Page(source)
            with self.subTest(page=filename):
                self.assertIn('lang="en"',source)
                self.assertEqual(sum(1 for tag,a in page.tags if tag=="nav" and a.get("class")=="language-switch"),1)
                languages={a["hreflang"] for tag,a in page.tags if tag=="link" and a.get("rel")=="alternate"}
                self.assertEqual(languages,{"it","en","x-default"})
                for tag,attrs in page.tags:
                    value=attrs.get("src") or attrs.get("href")
                    if not value:
                        continue
                    parsed=urlsplit(value)
                    if parsed.scheme or not parsed.path:
                        continue
                    target=(path.parent/unquote(parsed.path)).resolve()
                    self.assertTrue(target.is_file(),value)
                if filename!="payment.html":
                    self.assertLess(source.index('src="../i18n.js"'),source.index('src="../site.js"'))
                self.assertNotIn('href="https://www.booking.com/"',source)
    def test_option_identifiers_remain_italian(self):
        page=Page((ROOT/"en/index.html").read_text())
        options=[a.get("value") for tag,a in page.tags if tag=="option"]
        self.assertIn("Tutti gli appartamenti",options)
        self.assertIn("Suite Max",options)

