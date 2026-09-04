"""Check deployed static links and resources without submitting forms."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get("TEST_URL","https://dai-squee.vercel.app")
class Links(HTMLParser):
    def __init__(self,text):
        super().__init__()
        self.urls=[]
        self.ids=set()
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if "id" in values:self.ids.add(values["id"])
        for key in ("href","src"):
            if values.get(key):self.urls.append(values[key])

urls=set()
fragments=[]
for path in (ROOT/"public").rglob("*.html"):
    relative=path.relative_to(ROOT/"public").as_posix()
    page=Links(path.read_text())
    for href in page.urls:
        target=urljoin(BASE+"/"+relative,href)
        parsed=urlsplit(target)
        if parsed.scheme not in ("http","https"):continue
        urls.add(parsed._replace(fragment="").geturl())
        if parsed.netloc==urlsplit(BASE).netloc and parsed.fragment:
            local=ROOT/"public"/unquote(parsed.path.lstrip("/") or "index.html")
            if local.is_file() and local.suffix==".html" and parsed.fragment not in Links(local.read_text()).ids:
                fragments.append({"page":relative,"target":href})
results=[]
for url in sorted(urls):
    internal=urlsplit(url).netloc==urlsplit(BASE).netloc
    try:
        response=urlopen(Request(url,method="HEAD",headers={"User-Agent":"Mozilla/5.0 DaiSquee-LinkCheck"}),timeout=12)
        code=response.status
    except HTTPError as error:code=error.code
    except (URLError,TimeoutError,OSError):code="unverified"
    results.append({"url":url,"status":code,"internal":internal})
report={"checked":len(results),"internal_failures":[r for r in results if r["internal"] and r["status"]!=200],"external_unverified":[r for r in results if not r["internal"] and r["status"]!=200],"fragment_failures":fragments}
(ROOT/"test-results").mkdir(exist_ok=True)
(ROOT/"test-results/link-audit.json").write_text(json.dumps({"summary":report,"results":results},indent=2))
print(json.dumps(report,indent=2))

