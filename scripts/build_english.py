"""Build static English pages and matching Italian language links."""
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://www.daisquee.it"
PAGES = dict(zip(
    "index chi-siamo appartamenti appartamento-suite-max appartamento-michele appartamento-rosa-e-romeo intorno-a-noi amici-partners servizi contatti domande-frequenti prenota disponibilita pagamento possagno-canova bassano-del-grappa asolo maser-palladio carlo-scarpa-brion monte-grappa pedemontana-in-bici terre-del-prosecco navigazione-stefanato flyvenice airsports-montegrappa rafting-brenta".split(),
    "index about apartments suite-max michele rosa-e-romeo explore friends-and-partners amenities contact faq book availability payment possagno-canova bassano-del-grappa asolo maser-palladio carlo-scarpa-brion monte-grappa cycling prosecco-country navigazione-stefanato flyvenice airsports-montegrappa rafting-brenta".split()
))
PAGES = {key+".html": value+".html" for key, value in PAGES.items()}
TRANSLATIONS = json.loads((ROOT/"translations/en.json").read_text())

def translate(value):
    normalized = " ".join(value.split())
    if not normalized:
        return value
    replacement = TRANSLATIONS.get(normalized, normalized)
    return value[:len(value)-len(value.lstrip())] + replacement + value[len(value.rstrip()):]

def url(value):
    parsed = urlsplit(value)
    if parsed.scheme and not value.startswith(ORIGIN+"/"):
        return value
    if not parsed.path:
        return value
    path = parsed.path.lstrip("/")
    if path in PAGES or (parsed.netloc and not path):
        path = PAGES.get(path, "index.html")
        if parsed.netloc:
            path = "/en/" + ("" if path == "index.html" else path)
    elif path == "en" or path.startswith("en/"):
        return value
    elif parsed.netloc:
        return value
    else:
        path = "../" + path
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

def structured(value, key=""):
    if isinstance(value, dict):
        return {k: structured(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [structured(v, key) for v in value]
    if isinstance(value, str):
        if key == "inLanguage":
            return "en-GB"
        if value.startswith(ORIGIN+"/"):
            return url(value)
        return translate(value)
    return value

class English(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.raw = None
        self.jsonld = False
    def handle_decl(self, decl):
        self.parts.append("<!"+decl+">")
    def handle_comment(self, data):
        self.parts.append("<!--"+data+"-->")
    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs, False)
    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, True)
    def start(self, tag, attrs, closed):
        attrs = dict(attrs)
        if tag == "html":
            attrs["lang"] = "en"
        if tag in ("script", "style"):
            self.raw = tag
            self.jsonld = attrs.get("type") == "application/ld+json"
        # Option values are stable backend identifiers, not translated labels.
        if tag == "option" and "value" not in attrs:
            source = self.get_starttag_text()
            pos = self.getpos()
            lines = self.source.splitlines(keepends=True)
            start = sum(map(len, lines[:pos[0]-1]))+pos[1]+len(source)
            attrs["value"] = html.unescape(self.source[start:self.source.index("</option>", start)]).strip()
        for key, value in list(attrs.items()):
            if value is None:
                continue
            if key in ("href", "src", "action"):
                attrs[key] = url(value)
            elif key in ("alt", "aria-label", "placeholder", "title"):
                attrs[key] = translate(value)
            elif tag == "meta" and key == "content":
                attrs[key] = url(value) if value.startswith(ORIGIN+"/") else translate(value)
        if tag == "meta" and attrs.get("property") == "og:locale":
            attrs["content"] = "en_GB"
        self.parts.append("<"+tag+"".join(" "+k+('="'+html.escape(v, quote=True)+'"' if v is not None else "") for k,v in attrs.items())+(" />" if closed else ">"))
    def handle_endtag(self, tag):
        self.parts.append("</"+tag+">")
        if tag == self.raw:
            self.raw = None
    def handle_data(self, data):
        if self.raw:
            self.parts.append(json.dumps(structured(json.loads(data)), ensure_ascii=False) if self.jsonld else data)
        else:
            self.parts.append(html.escape(translate(data), quote=False))
    def convert(self, source):
        self.source = source
        self.feed(source)
        return "".join(self.parts)

def decorate(source, filename, english=False):
    source = re.sub(r'<link[^>]*data-language-alternate[^>]*>\s*', '', source)
    source = re.sub(r'<nav class="language-switch".*?</nav>', '', source, flags=re.S)
    source = re.sub(r'<script[^>]*src="(?:\.\./)?i18n.js"[^>]*></script>\s*', '', source)
    it = ORIGIN + "/" + ("" if filename == "index.html" else filename)
    en = ORIGIN + "/en/" + ("" if filename == "index.html" else PAGES[filename])
    alternates = "".join('<link rel="alternate" hreflang="'+lang+'" href="'+href+'" data-language-alternate />' for lang,href in (("it",it),("en",en),("x-default",it)))
    source = source.replace("</head>", alternates+"</head>")
    it_href = "../"+filename if english else filename
    en_href = PAGES[filename] if english else "en/"+PAGES[filename]
    switch = '<nav class="language-switch" aria-label="'+("Language" if english else "Lingua")+'"><a href="'+it_href+'" lang="it" hreflang="it" data-language-link'+('' if english else ' aria-current="page"')+'>IT</a><span aria-hidden="true">/</span><a href="'+en_href+'" lang="en" hreflang="en" data-language-link'+(' aria-current="page"' if english else '')+'>EN</a></nav>'
    if '<div class="header-actions">' in source:
        source = source.replace('<div class="header-actions">','<div class="header-actions">'+switch,1)
    else:
        source = source.replace('</header>',switch+'</header>',1)
    script = '<script src="'+("../" if english else "")+'i18n.js"></script>'
    if '<script src="' in source:
        source = source.replace('<script src="',script+'<script src="',1)
    else:
        source = source.replace("</body>",script+"</body>")
    return source

def build():
    (ROOT/"en").mkdir(exist_ok=True)
    for filename, output in PAGES.items():
        source = (ROOT/filename).read_text()
        # Strip generated navigation before translating.
        source = re.sub(r'<link[^>]*data-language-alternate[^>]*>\s*', '', source)
        source = re.sub(r'<nav class="language-switch".*?</nav>', '', source, flags=re.S)
        source = re.sub(r'<script[^>]*src="i18n.js"[^>]*></script>\s*', '', source)
        english = decorate(English().convert(source),filename,True)
        (ROOT/"en"/output).write_text(english)
        (ROOT/filename).write_text(decorate(source,filename))
    runtime = """const DaiLocale = (() => {
  const language = document.documentElement.lang === 'en' ? 'en' : 'it';
  const translations = DICTIONARY;
  const pages = PAGES;
  const t = text => language === 'en' ? (translations[text] ?? text) : text;
  const page = file => language === 'en' ? (pages[file] || file) : file;
  document.querySelectorAll('[data-language-link]').forEach(link => {
    const update = () => {
      const target = new URL(link.href);
      target.search = location.search;
      target.hash = location.hash;
      if (!target.searchParams.has('receipt')) {
        const fields = {apartment: ['calendarApartment','stayType'], checkin: ['arrivalDate','checkin'], checkout: ['departureDate','checkout'], guests: ['bookingGuests','guests']};
        for (const [key, ids] of Object.entries(fields)) {
          const field = ids.map(id=>document.getElementById(id)).find(Boolean);
          if (field?.value) target.searchParams.set(key, key === 'guests' ? field.value.split(' ')[0] : field.value);
        }
      }
      link.href = target.href;
    };
    update();
    link.addEventListener('click', update);
  });
  return {language, locale: language === 'en' ? 'en-GB' : 'it-IT', t, page};
})();
"""
    runtime = runtime.replace("DICTIONARY",json.dumps(TRANSLATIONS,ensure_ascii=False)).replace("PAGES",json.dumps(PAGES))
    (ROOT/"i18n.js").write_text(runtime)
    import xml.etree.ElementTree as ET
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("",namespace)
    tree = ET.parse(ROOT/"sitemap.xml")
    for child in list(tree.getroot()):
        loc = child.find("{"+namespace+"}loc")
        if loc is not None and "/en/" in loc.text:
            tree.getroot().remove(child)
    for filename in PAGES.values():
        if filename == "payment.html":
            continue
        entry = ET.SubElement(tree.getroot(),"{"+namespace+"}url")
        ET.SubElement(entry,"{"+namespace+"}loc").text = ORIGIN+"/en/"+("" if filename=="index.html" else filename)
    tree.write(ROOT/"sitemap.xml",encoding="unicode",xml_declaration=True)
    print("Generated",len(PAGES),"English pages.")

if __name__ == "__main__":
    build()
