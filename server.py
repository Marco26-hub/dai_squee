"""Dai Squee: static site, reservations, private administration and integrations."""
import base64
import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP
import mimetypes
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from datetime import date, datetime, timezone
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DAISQUE_DATA_DIR", str(ROOT / ".local-data")))
ROOMS = ("Suite Max", "Michele", "Rosa e Romeo")
ROOM_SLUGS = dict(zip(("suite-max", "michele", "rosa-e-romeo"), ROOMS))
CHANNELS = ("booking", "airbnb")
SECRETS = ("stripe_secret", "stripe_webhook_secret", "smtp_password")
DEFAULTS = {
    "business_name": "Dai Squee", "email": "info@daisquee.it", "phone": "+39 349 4454604",
    "address": "Viale A. Canova 51, 31054 Possagno (TV)", "site_url": ("https://"+os.environ["VERCEL_PROJECT_PRODUCTION_URL"]) if os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") else "",
    "stripe_secret": "", "stripe_webhook_secret": "", "smtp_host": "", "smtp_port": 587,
    "smtp_user": "", "smtp_password": "", "smtp_from": "", "smtp_mode": "starttls",
    "booking_url": "https://www.booking.com/", "airbnb_url": "https://www.airbnb.it/",
    "vrbo_url": "https://www.vrbo.com/", "rates": {room: None for room in ROOMS},
    "direct_enabled": False, "payment_methods": [], "booking_terms": "", "booking_terms_en": "",
    "bank_iban": "", "bank_holder": "", "bank_instructions": "", "bank_instructions_en": "",
    "capacities": {"Suite Max": 4, "Michele": 2, "Rosa e Romeo": 2}
}
ATTEMPTS = {}
DATABASE_URL = os.environ.get("DATABASE_URL", "")
INITIALIZED = False
def now():
    return datetime.now(timezone.utc).isoformat()
def db():
    if DATABASE_URL:
        return PostgresConnection()
    conn = sqlite3.connect(DATA / "reservations.sqlite", timeout=20)
    conn.row_factory = sqlite3.Row
    return conn
class PostgresConnection:
    def __init__(self):
        import psycopg
        from psycopg.rows import dict_row
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    def execute(self, query, params=()):
        if query == "BEGIN IMMEDIATE":
            return self.conn.execute("SELECT pg_advisory_xact_lock(73462051)")
        return self.conn.execute(query.replace("?", "%s"), params)
    def executescript(self, script):
        for statement in script.replace("id INTEGER PRIMARY KEY", "id BIGSERIAL PRIMARY KEY").split(";"):
            if statement.strip():
                self.conn.execute(statement)
    def __enter__(self):
        return self
    def __exit__(self, kind, value, tb):
        if kind:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000).hex()
def init():
    global INITIALIZED
    if INITIALIZED:
        return
    if os.environ.get("VERCEL") and not DATABASE_URL:
        raise ApiError(503, "Archivio non collegato. Configurare DATABASE_URL nel progetto Vercel.")
    if not DATABASE_URL:
        DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(DATA, 0o700)
    with db() as conn:
        # Serialize schema initialization across concurrent serverless workers.
        if DATABASE_URL:
            conn.execute("SELECT pg_advisory_xact_lock(73462052)")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL, csrf TEXT);
        CREATE TABLE IF NOT EXISTS bookings (
          id TEXT PRIMARY KEY, request_key TEXT UNIQUE, created_at TEXT, updated_at TEXT,
          name TEXT, email TEXT, phone TEXT, apartment TEXT, checkin TEXT, checkout TEXT,
          guests INTEGER, channel TEXT, message TEXT, status TEXT DEFAULT 'pending',
          amount_cents INTEGER, notes TEXT DEFAULT '', checkout_id TEXT, checkout_url TEXT,
          paid_at TEXT, payment_id TEXT, invoice_file TEXT, invoice_name TEXT,
          invoice_sent_at TEXT, email_error TEXT, payment_email_at TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, booking_id TEXT, action TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS stripe_events (id TEXT PRIMARY KEY, created_at TEXT);
        CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT, occurred REAL);
        CREATE TABLE IF NOT EXISTS checkout_attempts (booking_id TEXT PRIMARY KEY, generation INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS direct_details (booking_id TEXT PRIMARY KEY, method TEXT, terms TEXT, access_token TEXT UNIQUE, expires_at INTEGER, email_attempted INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS apartment_photos (id TEXT PRIMARY KEY, apartment TEXT, role TEXT, caption TEXT, mime TEXT, data TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS photo_translations (photo_id TEXT PRIMARY KEY, caption_en TEXT);
        CREATE TABLE IF NOT EXISTS booking_languages (booking_id TEXT PRIMARY KEY, language TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_connections (
          apartment TEXT NOT NULL, channel TEXT NOT NULL, listing_id TEXT NOT NULL DEFAULT '',
          import_url TEXT NOT NULL DEFAULT '', updated_at TEXT, version INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(apartment,channel));
        CREATE TABLE IF NOT EXISTS calendar_exports (apartment TEXT PRIMARY KEY, token TEXT UNIQUE, updated_at TEXT);
        """)
        for room in ROOMS:
            for channel in CHANNELS:
                conn.execute("INSERT INTO channel_connections(apartment,channel) VALUES (?,?) ON CONFLICT(apartment,channel) DO NOTHING", (room,channel))
        for key, value in DEFAULTS.items():
            conn.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO NOTHING", (key, json.dumps(value)))
        if not conn.execute("SELECT 1 FROM settings WHERE key='password_hash'").fetchone():
            password = os.environ.get("ADMIN_INITIAL_PASSWORD") or secrets.token_urlsafe(18)
            if DATABASE_URL and not os.environ.get("ADMIN_INITIAL_PASSWORD"):
                raise ApiError(503, "Configurare ADMIN_INITIAL_PASSWORD prima del primo accesso.")
            salt = secrets.token_hex(16)
            for key, value in (("password_hash", password_hash(password, salt)), ("password_salt", salt)):
                conn.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO NOTHING", (key, json.dumps(value)))
            if not DATABASE_URL:
                credential = DATA / "admin-access.txt"
                credential.write_text("Dai Squee - accesso amministrazione\nUtente: admin\nPassword: " + password + "\nCambiare la password in Impostazioni.\n")
                os.chmod(credential, 0o600)
    if not DATABASE_URL:
        os.chmod(DATA / "reservations.sqlite", 0o600)
    INITIALIZED = True
def settings():
    with db() as conn:
        return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM settings")}
def audit(conn, booking_id, action):
    conn.execute("INSERT INTO events(booking_id,action,created_at) VALUES (?,?,?)", (booking_id, action, now()))
def booking(conn, booking_id):
    row = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not row:
        raise ApiError(404, "Prenotazione non trovata.")
    return dict(row)
def overlap(conn, room, checkin, checkout, exclude=""):
    return conn.execute("SELECT id FROM bookings WHERE apartment=? AND id!=? AND status IN ('confirmed','blocked') AND checkin<? AND checkout>? LIMIT 1", (room, exclude, checkout, checkin)).fetchone()

def direct_quote(payload, conf):
    language = "en" if payload.get("language") == "en" else "it"
    terms = conf.get("booking_terms_en", "") if language == "en" else conf["booking_terms"]
    instructions = conf.get("bank_instructions_en", "") if language == "en" else conf["bank_instructions"]
    room, arrival, departure, guests = validate_stay(payload)
    if room not in ROOMS:
        raise ApiError(400, "Selezionare un appartamento specifico.")
    if guests > conf["capacities"][room]:
        raise ApiError(400, "Numero ospiti superiore alla capienza configurata per questo appartamento.")
    rate = conf["rates"].get(room)
    if not conf["direct_enabled"] or not rate or not conf["booking_terms"].strip():
        raise ApiError(503, "Prenotazione immediata non disponibile per questo appartamento. Contattateci per una proposta.")
    if not terms.strip():
        raise ApiError(503, "English booking terms are not available yet. Please contact us for an offer.")
    methods = list(conf["payment_methods"])
    if not all(conf[k] for k in ("stripe_secret", "stripe_webhook_secret", "site_url")):
        methods = [m for m in methods if m != "card"]
    if not conf["bank_iban"] or not conf["bank_holder"] or not instructions:
        methods = [m for m in methods if m != "bank"]
    if not methods:
        raise ApiError(503, "Modalità di pagamento non ancora disponibili. Contattate la struttura.")
    nights = (date.fromisoformat(departure)-date.fromisoformat(arrival)).days
    amount = int((Decimal(str(rate))*100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))*nights
    return {"language":language,"apartment":room,"checkin":arrival,"checkout":departure,"guests":guests,"nights":nights,"amount_cents":amount,"methods":methods,"terms":terms,"bank_iban":conf["bank_iban"] if "bank" in methods else "","bank_holder":conf["bank_holder"] if "bank" in methods else "","bank_instructions":instructions if "bank" in methods else ""}

def booking_language(bid):
    with db() as conn:
        row = conn.execute("SELECT language FROM booking_languages WHERE booking_id=?",(bid,)).fetchone()
        if row:
            return row["language"]
        direct = conn.execute("SELECT terms FROM direct_details WHERE booking_id=?",(bid,)).fetchone()
    return json.loads(direct["terms"]).get("language", "it") if direct else "it"

def validate_channel_url(value, channel):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 for c in value):
        raise ApiError(400,"Link calendario non valido.")
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        base = "booking.com" if channel == "booking" else "airbnb.com"
        valid_host = host == base or host.endswith("."+base)
        if parsed.scheme != "https" or not valid_host or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment or parsed.path in ("","/"):
            raise ValueError()
    except ValueError:
        raise ApiError(400,"Inserire il link HTTPS del calendario esportato dal portale, senza credenziali personali.")
    return parsed._replace(netloc=host).geturl()

def channel_manager_config(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='channel_manager_draft'").fetchone()
    return json.loads(row["value"]) if row else {"provider":"","account_ref":"","mappings":{room:"" for room in ROOMS},"version":0}

def channels_state():
    with db() as conn:
        connections = [dict(row) for row in conn.execute("SELECT * FROM channel_connections ORDER BY apartment,channel")]
        exports = {row["apartment"]:dict(row) for row in conn.execute("SELECT * FROM calendar_exports")}
        manager = channel_manager_config(conn)
    for row in connections:
        row["import_configured"] = bool(row.pop("import_url"))
        row["status"] = "prepared" if row["import_configured"] or row["listing_id"] else "not_configured"
        row["last_sync"] = None
    base = settings()["site_url"].rstrip("/")
    return {"connections":connections,"exports":[{"apartment":room,"active":bool(exports.get(room,{}).get("token")),"url":base+"/api/calendar/"+exports[room]["token"]+".ics" if base and exports.get(room,{}).get("token") else ""} for room in ROOMS],
            "manager":manager,"import_active":False,"api_active":False,"site_url_configured":base.startswith("https://")}

def calendar_export(token):
    from icalendar import Calendar, Event
    with db() as conn:
        export = conn.execute("SELECT apartment FROM calendar_exports WHERE token=?",(token,)).fetchone()
        if not export:
            raise ApiError(404,"Calendario non disponibile.")
        rows = [dict(row) for row in conn.execute("SELECT id,checkin,checkout,updated_at FROM bookings WHERE apartment=? AND status IN ('confirmed','blocked') AND checkout>? ORDER BY checkin,id",(export["apartment"],date.today().isoformat()))]
    calendar = Calendar()
    calendar.add("prodid","-//Dai Squee//Property availability//EN")
    calendar.add("version","2.0")
    calendar.add("calscale","GREGORIAN")
    for row in rows:
        event = Event()
        event.add("uid",hashlib.sha256(("daisquee-calendar:"+row["id"]).encode()).hexdigest()+"@daisquee")
        event.add("dtstamp",datetime.fromisoformat(row["updated_at"]))
        event.add("dtstart",date.fromisoformat(row["checkin"]))
        event.add("dtend",date.fromisoformat(row["checkout"]))
        event.add("summary","Unavailable")
        event.add("transp","OPAQUE")
        calendar.add_component(event)
    return calendar.to_ical()

def quote_signature(quote, expires, conf):
    message = json.dumps([quote, expires], sort_keys=True, separators=(",", ":"))
    return hmac.new(conf["password_hash"].encode(),message.encode(),hashlib.sha256).hexdigest()

def direct_result(bid):
    with db() as conn:
        row = booking(conn,bid)
        detail = dict(conn.execute("SELECT * FROM direct_details WHERE booking_id=?",(bid,)).fetchone())
    result = {"reference":bid,"apartment":row["apartment"],"checkin":row["checkin"],"checkout":row["checkout"],"amount_cents":row["amount_cents"],"method":detail["method"],"status":row["status"],"paid":bool(row["paid_at"]),"terms":json.loads(detail["terms"]),"access_token":detail["access_token"],"url":row["checkout_url"] if not row["paid_at"] and row["status"]=="confirmed" else None,"email_error":row["email_error"]}
    return result

def direct_checkout(bid):
    conf = settings()
    with db() as conn:
        row = booking(conn,bid)
        detail = dict(conn.execute("SELECT * FROM direct_details WHERE booking_id=?",(bid,)).fetchone())
    if row["checkout_id"] and row["checkout_id"] != "creating":
        return
    if row["status"] != "confirmed":
        raise ApiError(409,"Prenotazione annullata. Selezionare nuovamente le date.")
    if detail["expires_at"] < time.time()+1805:
        raise ApiError(409,"Sessione non completata. Contattate la struttura con il riferimento "+bid+" prima di riprovare.")
    language = json.loads(detail["terms"]).get("language", "it")
    receipt_path = "/en/book.html?receipt=" if language == "en" else "/prenota.html?receipt="
    result = stripe_request("checkout/sessions", {
        "mode":"payment", "payment_method_types[0]":"card", "locale":language,
        "client_reference_id":bid,"customer_email":row["email"],
        "expires_at":detail["expires_at"],
        "line_items[0][price_data][currency]":"eur",
        "line_items[0][price_data][unit_amount]":row["amount_cents"],
        "line_items[0][price_data][product_data][name]":"Dai Squee - "+row["apartment"],
        "line_items[0][price_data][product_data][description]":row["checkin"]+" / "+row["checkout"],
        "line_items[0][quantity]":1,"metadata[booking_id]":bid,
        "success_url":conf["site_url"].rstrip("/")+receipt_path+detail["access_token"],
        "cancel_url":conf["site_url"].rstrip("/")+receipt_path+detail["access_token"]
    }, key="direct-"+bid)
    with db() as conn:
        conn.execute("UPDATE bookings SET checkout_id=?,checkout_url=? WHERE id=?",(result["id"],result["url"],bid))
        audit(conn,bid,"Checkout carta diretto: date riservate fino a esito Stripe")

def direct_email(bid):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        detail = conn.execute("SELECT * FROM direct_details WHERE booking_id=?",(bid,)).fetchone()
        if not detail or detail["email_attempted"]:
            return
        conn.execute("UPDATE direct_details SET email_attempted=1 WHERE booking_id=?",(bid,))
        row = booking(conn,bid)
    conf = settings()
    terms = json.loads(detail["terms"])
    content = "Prenotazione "+bid+"\n"+row["apartment"]+"\n"+row["checkin"]+" / "+row["checkout"]+"\nTotale EUR "+format(row["amount_cents"]/100,".2f")+"\nPagamento: "+{"arrival":"all'arrivo","bank":"bonifico","card":"carta verificata"}[detail["method"]]+"\n\n"+terms["terms"]
    if detail["method"]=="bank":
        content += "\n\n"+terms["bank_holder"]+"\nIBAN: "+terms["bank_iban"]+"\nCausale: "+bid+"\n"+terms["bank_instructions"]
    english = terms.get("language") == "en"
    if english:
        content = "Booking "+bid+"\n"+row["apartment"]+"\n"+row["checkin"]+" / "+row["checkout"]+"\nTotal EUR "+format(row["amount_cents"]/100,".2f")+"\nPayment: "+{"arrival":"on arrival","bank":"bank transfer","card":"card payment verified"}[detail["method"]]+"\n\n"+terms["terms"]
        if detail["method"] == "bank":
            content += "\n\n"+terms["bank_holder"]+"\nIBAN: "+terms["bank_iban"]+"\nPayment reference: "+bid+"\n"+terms["bank_instructions"]
    try:
        send_mail(row["email"],("Dai Squee - booking " if english else "Dai Squee - prenotazione ")+bid,content)
        with db() as conn:
            conn.execute("UPDATE bookings SET email_error=NULL WHERE id=?",(bid,))
            audit(conn,bid,"Conferma diretta accettata da SMTP")
    except ApiError as error:
        with db() as conn:
            conn.execute("UPDATE bookings SET email_error=? WHERE id=?",(error.message,bid))
            audit(conn,bid,"Invio conferma fallito o incerto: verificare prima di reinviare")
class ApiError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
def text_value(payload, field, limit, required=False):
    value = payload.get(field, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ApiError(400, "Controllare il campo " + field + ".")
    return value.strip()
def validate_stay(payload, admin=False):
    room = payload.get("apartment")
    if room not in ROOMS + (("Tutti gli appartamenti",) if not admin else ()):
        raise ApiError(400, "Selezionare un appartamento.")
    try:
        arrival, departure = date.fromisoformat(payload["checkin"]), date.fromisoformat(payload["checkout"])
        guests = int(payload.get("guests", 1))
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "Date o numero ospiti non validi.")
    if departure <= arrival or (not admin and arrival < date.today()) or (departure-arrival).days > 365 or guests not in range(1, 5):
        raise ApiError(400, "Date o numero ospiti non validi.")
    return room, arrival.isoformat(), departure.isoformat(), guests
def stripe_request(path, params=None, key=None):
    config = settings()
    if not config["stripe_secret"]:
        raise ApiError(503, "Configurare Stripe in Impostazioni.")
    headers = {"Authorization": "Bearer " + config["stripe_secret"]}
    if key:
        headers["Idempotency-Key"] = key
    data = urlencode(params).encode() if params is not None else None
    try:
        with urlopen(Request("https://api.stripe.com/v1/" + path, data=data, headers=headers), timeout=20) as response:
            return json.load(response)
    except HTTPError:
        raise ApiError(502, "Stripe non ha completato l'operazione. Verificare configurazione e dashboard Stripe, poi riprovare.")
    except (URLError, TimeoutError):
        raise ApiError(502, "Esito Stripe non disponibile. Riprovare la stessa operazione senza modificarne l'importo.")
def send_mail(to, subject, content, attachment=None):
    config = settings()
    if not config["smtp_host"] or not config["smtp_from"]:
        raise ApiError(503, "Email non inviata: configurare server SMTP e mittente in Impostazioni.")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = config["smtp_from"], to, subject
    message.set_content(content)
    if attachment:
        filename, pdf = attachment
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    try:
        client = smtplib.SMTP_SSL if config["smtp_mode"] == "ssl" else smtplib.SMTP
        with client(config["smtp_host"], int(config["smtp_port"]), timeout=20) as smtp:
            if config["smtp_mode"] == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if config["smtp_user"]:
                smtp.login(config["smtp_user"], config["smtp_password"])
            refused = smtp.send_message(message)
            if refused:
                raise ApiError(502, "Il server email ha rifiutato il destinatario.")
    except (smtplib.SMTPException, OSError):
        raise ApiError(502, "Invio email non riuscito o esito incerto. Verificare SMTP e il destinatario prima di ritentare.")

class Handler(SimpleHTTPRequestHandler):
    server_version = "DaiSquee"
    def log_message(self, fmt, *args):
        # Keep personal data, tokens and request bodies out of access logs.
        pass
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()
    def response(self, status, payload, cookie=None):
        if status >= 400 and self.headers.get("Accept-Language", "").lower().startswith("en") and "error" in payload:
            translations = json.loads((ROOT / "translations/en.json").read_text())
            message = payload["error"]
            if message.startswith("Controllare il campo "):
                translated = "Please check the field: " + message.removeprefix("Controllare il campo ")
            elif message.startswith("English booking terms"):
                translated = message
            else:
                translated = translations.get(message, "The request could not be completed. Please try again or contact the host.")
            payload = {**payload, "error": translated}
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)
    def raw_body(self, limit=8*1024*1024):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Richiesta non valida.")
        if not 0 < size <= limit:
            raise ApiError(413, "Dimensione richiesta non consentita.")
        return self.rfile.read(size)
    def payload(self):
        try:
            value = json.loads(self.raw_body())
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Dati non validi.")
    def same_origin(self):
        expected = {"http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")}
        configured = settings()["site_url"].rstrip("/")
        if configured:
            expected.add(configured)
        origin = self.headers.get("Origin")
        if origin and origin not in expected:
            raise ApiError(403, "Origine della richiesta non autorizzata.")
    def session(self, mutate=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["daisquee_session"].value
        except Exception:
            raise ApiError(401, "Accedere all'area riservata.")
        with db() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise ApiError(401, "Sessione scaduta. Accedere nuovamente.")
        if mutate and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), row["csrf"]):
            raise ApiError(403, "Sessione non valida. Ricaricare la pagina.")
        return dict(row)
    def limited(self, label, maximum, window):
        ip = self.headers.get("x-vercel-forwarded-for", self.client_address[0]) if os.environ.get("VERCEL") else self.client_address[0]
        key = label + ":" + hashlib.sha256(ip.encode()).hexdigest()
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM rate_limits WHERE occurred<?",(time.time()-86400,))
            attempts = conn.execute("SELECT COUNT(*) AS count FROM rate_limits WHERE bucket=? AND occurred>?",(key,time.time()-window)).fetchone()["count"]
            if attempts >= maximum:
                raise ApiError(429, "Troppe richieste. Attendere e riprovare.")
            conn.execute("INSERT INTO rate_limits VALUES (?,?)",(key,time.time()))
    def do_GET(self):
        self.dispatch_app_request()
    def do_POST(self):
        self.dispatch_app_request()
    def do_PATCH(self):
        self.dispatch_app_request()
    def dispatch_app_request(self):
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                init()
                if self.command != "GET" and path != "/api/stripe/webhook":
                    self.same_origin()
                self.api(path)
            elif self.command == "GET":
                self.public_file(path)
            else:
                raise ApiError(405, "Metodo non consentito.")
        except ApiError as error:
            self.response(error.code, {"error": error.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print("Server error:", type(error).__name__, flush=True)
            self.response(500, {"error": "Operazione non completata. Riprovare o contattare la struttura."})
    def public_file(self, path):
        decoded = unquote(path).lstrip("/") or "index.html"
        if decoded in ("en", "en/"):
            decoded = "en/index.html"
        target = (ROOT / decoded).resolve()
        allowed = {".html", ".css", ".js", ".jpg", ".jpeg", ".png", ".webp", ".ico", ".svg", ".woff2"}
        if not target.is_relative_to(ROOT) or not target.is_file() or not (target.parent == ROOT or target.is_relative_to(ROOT / "assets") or (target.parent == ROOT / "en" and target.suffix == ".html")) or (target.suffix not in allowed and target.name not in ("robots.txt", "sitemap.xml", "llms.txt")):
            self.send_error(404, "Pagina non trovata")
            return
        body = target.read_bytes()
        if target.suffix in (".html", ".xml") or target.name in ("robots.txt","llms.txt"):
            base = settings()["site_url"].rstrip("/")
            if base:
                value = body.decode()
                if target.suffix != ".html":
                    value = value.replace("https://www.daisquee.it", base)
                else:
                    for suffix in ("/appartamento-", "/assets/", "/#", '/"', '/&'):
                        value = value.replace("https://www.daisquee.it"+suffix, base+suffix)
                body = value.encode()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(target.name)[0] or "application/octet-stream") + ("; charset=utf-8" if target.suffix in (".html",".css",".js",".xml",".txt") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if target.suffix in (".html",".js",".css") else "public, max-age=86400")
        if target.name in ("admin.html", "pagamento.html"):
            self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(body)
    def api(self, path):
        method = self.command
        export_match = re.fullmatch(r"/api/calendar/([A-Za-z0-9_-]{43})\.ics",path)
        if export_match and method == "GET":
            body = calendar_export(export_match.group(1))
            self.send_response(200)
            self.send_header("Content-Type","text/calendar; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Robots-Tag","noindex, nofollow")
            self.send_header("Content-Disposition",'attachment; filename="availability.ics"')
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/api/apartment-photos" and method == "GET":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT p.id,p.apartment,p.role,p.caption,t.caption_en FROM apartment_photos p LEFT JOIN photo_translations t ON t.photo_id=p.id ORDER BY p.created_at,p.id")]
            return self.response(200,{"photos":rows})
        image_match = re.fullmatch(r"/api/photos/([a-f0-9]{24})",path)
        if image_match and method == "GET":
            with db() as conn:
                row = conn.execute("SELECT mime,data FROM apartment_photos WHERE id=?",(image_match.group(1),)).fetchone()
            if not row:
                raise ApiError(404,"Foto non trovata.")
            body = base64.b64decode(row["data"])
            self.send_response(200)
            self.send_header("Content-Type",row["mime"])
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/health" and method == "GET":
            return self.response(200, {"ok": True})
        if path == "/api/config" and method == "GET":
            conf = settings()
            return self.response(200, {key: conf[key] for key in ("business_name","email","phone","address","booking_url","airbnb_url","vrbo_url")})
        if path == "/api/availability" and method == "GET":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT apartment,checkin,checkout FROM bookings WHERE status IN ('confirmed','blocked') AND checkout>=?", (date.today().isoformat(),))]
            conf = settings()
            return self.response(200, {"unavailable": rows,"updated_at":now(),"capacities":conf["capacities"],"direct_enabled":conf["direct_enabled"],"source":"property_calendar"})
        if path == "/api/quote" and method == "POST":
            conf = settings()
            quote = direct_quote(self.payload(),conf)
            with db() as conn:
                if overlap(conn,quote["apartment"],quote["checkin"],quote["checkout"]):
                    raise ApiError(409,"Il periodo selezionato non è disponibile.")
            expires = int(time.time())+900
            return self.response(200,{"quote":quote,"expires":expires,"signature":quote_signature(quote,expires,conf)})
        if path == "/api/reservation" and method == "GET":
            token = parse_qs(urlparse(self.path).query).get("token",[""])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{30,100}",token):
                raise ApiError(404,"Prenotazione non trovata.")
            with db() as conn:
                row = conn.execute("SELECT booking_id FROM direct_details WHERE access_token=?",(token,)).fetchone()
            if not row:
                raise ApiError(404,"Prenotazione non trovata.")
            return self.response(200,direct_result(row["booking_id"]))
        if path == "/api/reserve" and method == "POST":
            self.limited("direct",12,3600)
            p = self.payload()
            key = self.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}",key):
                raise ApiError(400,"Identificativo richiesta non valido.")
            with db() as conn:
                existing = conn.execute("SELECT b.id FROM bookings b JOIN direct_details d ON d.booking_id=b.id WHERE request_key=?",(key,)).fetchone()
            if existing:
                bid = existing["id"]
            else:
                conf = settings()
                quote = direct_quote(p,conf)
                expires = p.get("expires")
                signature = p.get("signature","")
                if type(expires) is not int or expires < time.time() or expires > time.time()+901 or not isinstance(signature,str) or not hmac.compare_digest(signature,quote_signature(quote,expires,conf)):
                    raise ApiError(409,"La proposta è scaduta o le condizioni sono cambiate. Verificare nuovamente il totale.")
                payment_method = p.get("payment_method")
                if payment_method not in quote["methods"] or p.get("consent") is not True or p.get("terms_consent") is not True:
                    raise ApiError(400,"Selezionare il pagamento e accettare le condizioni.")
                name,email,phone = text_value(p,"name",120,True),text_value(p,"email",254,True),text_value(p,"phone",40)
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
                    raise ApiError(400,"Email non valida.")
                with db() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute("SELECT id FROM bookings WHERE request_key=?",(key,)).fetchone()
                    if existing:
                        bid = existing["id"]
                    else:
                        if overlap(conn,quote["apartment"],quote["checkin"],quote["checkout"]):
                            raise ApiError(409,"Queste date sono appena state occupate. Scegliere un altro periodo.")
                        bid = "DS-"+secrets.token_hex(6).upper()
                        conn.execute("INSERT INTO bookings(id,request_key,created_at,updated_at,name,email,phone,apartment,checkin,checkout,guests,channel,message,status,amount_cents,checkout_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(bid,key,now(),now(),name,email,phone,quote["apartment"],quote["checkin"],quote["checkout"],quote["guests"],"Diretto online",text_value(p,"message",2000),"confirmed",quote["amount_cents"],"creating" if payment_method=="card" else None))
                        conn.execute("INSERT INTO direct_details(booking_id,method,terms,access_token,expires_at) VALUES (?,?,?,?,?)",(bid,payment_method,json.dumps(quote),secrets.token_urlsafe(32),int(time.time())+2400))
                        audit(conn,bid,"Prenotazione diretta: "+payment_method+". Condizioni accettate e archiviate.")
            result = direct_result(bid)
            if result["method"]=="card" and not result["paid"] and result["status"]=="confirmed":
                direct_checkout(bid)
            elif result["status"]=="confirmed":
                direct_email(bid)
            return self.response(200,direct_result(bid))
        if path == "/api/bookings" and method == "POST":
            self.limited("booking", 12, 3600)
            p = self.payload()
            if p.get("consent") is not True:
                raise ApiError(400, "Leggere l'informativa privacy.")
            room, arrival, departure, guests = validate_stay(p)
            name, email = text_value(p,"name",120,True), text_value(p,"email",254,True)
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise ApiError(400, "Email non valida.")
            key = self.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
                raise ApiError(400, "Identificativo richiesta non valido. Ricaricare la pagina.")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT id FROM bookings WHERE request_key=?", (key,)).fetchone()
                if existing:
                    return self.response(200, {"reference": existing["id"]})
                if room in ROOMS and overlap(conn, room, arrival, departure):
                    raise ApiError(409, "L'appartamento non è disponibile per queste date. Scegliete altre date o un altro appartamento.")
                bid = "DS-" + secrets.token_hex(4).upper()
                rate = settings()["rates"].get(room)
                amount = round(rate * (date.fromisoformat(departure)-date.fromisoformat(arrival)).days * 100) if rate else None
                conn.execute("INSERT INTO bookings(id,request_key,created_at,updated_at,name,email,phone,apartment,checkin,checkout,guests,channel,message,amount_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (bid,key,now(),now(),name,email,text_value(p,"phone",40),room,arrival,departure,guests,text_value(p,"channel",40),text_value(p,"message",2000),amount))
                conn.execute("INSERT INTO booking_languages VALUES (?,?)",(bid,"en" if p.get("language") == "en" else "it"))
                audit(conn,bid,"Richiesta registrata; informativa privacy accettata")
            return self.response(201, {"reference": bid})
        if path == "/api/admin/login" and method == "POST":
            self.limited("login", 8, 900)
            p, conf = self.payload(), settings()
            password = text_value(p,"password",500,True)
            if p.get("username") != "admin" or not hmac.compare_digest(password_hash(password,conf["password_salt"]),conf["password_hash"]):
                raise ApiError(401, "Credenziali non valide.")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
                conn.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(),time.time()+8*3600,csrf))
            secure = "; Secure" if os.environ.get("VERCEL") or settings()["site_url"].startswith("https://") else ""
            return self.response(200, {"csrf":csrf}, "daisquee_session="+token+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"+secure)
        if path == "/api/stripe/webhook" and method == "POST":
            return self.webhook()
        if not path.startswith("/api/admin/"):
            raise ApiError(404, "Risorsa non trovata.")
        session = self.session(method != "GET")
        if path == "/api/admin/channels" or path.startswith("/api/admin/channels/"):
            return self.manage_channels(path,method)
        if path == "/api/admin/session" and method == "GET":
            return self.response(200, {"csrf":session["csrf"]})
        if path == "/api/admin/logout" and method == "POST":
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
            return self.response(200, {"ok":True}, "daisquee_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path == "/api/admin/settings":
            return self.manage_settings(method)
        if path == "/api/admin/photos" and method == "GET":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT p.id,p.apartment,p.role,p.caption,t.caption_en FROM apartment_photos p LEFT JOIN photo_translations t ON t.photo_id=p.id ORDER BY p.created_at,p.id")]
            return self.response(200,{"photos":rows})
        if path == "/api/admin/photos" and method == "POST":
            p = self.payload()
            room, role = p.get("apartment"), p.get("role")
            caption = text_value(p,"caption",240,True)
            caption_en = text_value(p,"caption_en",240)
            if room not in ROOMS or role not in ("cover","gallery"):
                raise ApiError(400,"Appartamento o tipo foto non valido.")
            try:
                data = base64.b64decode(p.get("image",""),validate=True)
            except (ValueError,TypeError):
                raise ApiError(400,"Immagine non valida.")
            mime = "image/jpeg" if data.startswith(b"\xff\xd8\xff") else "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/webp" if data.startswith(b"RIFF") and data[8:12]==b"WEBP" else None
            if not mime or not 100<len(data)<=3*1024*1024:
                raise ApiError(400,"Caricare un'immagine JPG, PNG o WebP di massimo 3 MB.")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                count = conn.execute("SELECT COUNT(*) AS count FROM apartment_photos WHERE apartment=?",(room,)).fetchone()["count"]
                if count>=20:
                    raise ApiError(400,"Massimo 20 foto per appartamento. Rimuovere una foto prima di caricarne altre.")
                if role=="cover":
                    conn.execute("UPDATE apartment_photos SET role='gallery' WHERE apartment=?",(room,))
                pid = secrets.token_hex(12)
                conn.execute("INSERT INTO apartment_photos VALUES (?,?,?,?,?,?,?)",(pid,room,role,caption,mime,base64.b64encode(data).decode(),now()))
                conn.execute("INSERT INTO photo_translations VALUES (?,?)",(pid,caption_en))
                audit(conn,None,"Foto caricata: "+room+" / "+pid)
            return self.response(201,{"id":pid})
        photo_match = re.fullmatch(r"/api/admin/photos/([a-f0-9]{24})",path)
        if photo_match and method == "PATCH":
            p = self.payload()
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM apartment_photos WHERE id=?",(photo_match.group(1),)).fetchone()
                if not row:
                    raise ApiError(404,"Foto non trovata.")
                if p.get("remove") is True:
                    conn.execute("DELETE FROM apartment_photos WHERE id=?",(row["id"],))
                    conn.execute("DELETE FROM photo_translations WHERE photo_id=?",(row["id"],))
                else:
                    caption = text_value(p,"caption",240,True) if "caption" in p else row["caption"]
                    role = p.get("role",row["role"])
                    if role not in ("cover","gallery"):
                        raise ApiError(400,"Ruolo foto non valido.")
                    if role=="cover":
                        conn.execute("UPDATE apartment_photos SET role='gallery' WHERE apartment=?",(row["apartment"],))
                    conn.execute("UPDATE apartment_photos SET caption=?,role=? WHERE id=?",(caption,role,row["id"]))
                    if "caption_en" in p:
                        conn.execute("INSERT INTO photo_translations VALUES (?,?) ON CONFLICT(photo_id) DO UPDATE SET caption_en=excluded.caption_en",(row["id"],text_value(p,"caption_en",240)))
                audit(conn,None,"Foto aggiornata: "+row["id"])
            return self.response(200,{"ok":True})
        if path == "/api/admin/test-email" and method == "POST":
            conf = settings()
            send_mail(conf["email"], "Dai Squee - verifica email", "La configurazione email di Dai Squee funziona.")
            return self.response(200, {"message":"Email di prova accettata dal server SMTP."})
        if path == "/api/admin/bookings" and method == "GET":
            with db() as conn:
                rows = []
                for row in conn.execute("SELECT b.*,d.method AS payment_method,d.terms AS accepted_terms FROM bookings b LEFT JOIN direct_details d ON d.booking_id=b.id ORDER BY b.created_at DESC"):
                    item = dict(row)
                    item["has_invoice"] = bool(item.pop("invoice_file"))
                    rows.append(item)
            return self.response(200, {"bookings":rows})
        if path == "/api/admin/blocks" and method == "POST":
            p = self.payload()
            room, arrival, departure, guests = validate_stay(p,True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if overlap(conn,room,arrival,departure):
                    raise ApiError(409,"Le date si sovrappongono a una prenotazione o a un blocco.")
                bid = "BL-" + secrets.token_hex(4).upper()
                conn.execute("INSERT INTO bookings(id,created_at,updated_at,name,email,apartment,checkin,checkout,guests,channel,message,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (bid,now(),now(),"Blocco calendario","",room,arrival,departure,1,"Admin",text_value(p,"message",500),"blocked"))
                audit(conn,bid,"Date bloccate")
            return self.response(201, {"reference":bid})
        if path == "/api/admin/manual" and method == "POST":
            p=self.payload()
            room,arrival,departure,guests=validate_stay(p,True)
            name,email=text_value(p,"name",120,True),text_value(p,"email",254,True)
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
                raise ApiError(400,"Email non valida.")
            bid="DS-"+secrets.token_hex(4).upper()
            with db() as conn:
                conn.execute("INSERT INTO bookings(id,created_at,updated_at,name,email,phone,apartment,checkin,checkout,guests,channel,message) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(bid,now(),now(),name,email,text_value(p,"phone",40),room,arrival,departure,guests,text_value(p,"channel",40),text_value(p,"message",2000)))
                audit(conn,bid,"Prenotazione inserita manualmente dall'amministratore")
            return self.response(201,{"reference":bid})
        match = re.fullmatch(r"/api/admin/bookings/(DS-[A-F0-9]{8,12}|BL-[A-F0-9]{8})(?:/(events|checkout|invoice|send-invoice|send-payment|send-confirmation|sync-payment|expire-payment|record-payment))?", path)
        if match:
            return self.manage_booking(match.group(1),match.group(2),method)
        raise ApiError(404, "Risorsa non trovata.")
    def manage_settings(self, method):
        conf = settings()
        if method == "PATCH":
            p = self.payload()
            updates = {}
            for key in DEFAULTS:
                if key not in p:
                    continue
                value = p[key]
                if key in SECRETS and value == "":
                    continue
                if key == "direct_enabled":
                    if type(value) is not bool:
                        raise ApiError(400,"Abilitazione prenotazioni non valida.")
                elif key == "payment_methods":
                    if not isinstance(value,list) or any(v not in ("arrival","card","bank") for v in value) or len(value)!=len(set(value)):
                        raise ApiError(400,"Modalità di pagamento non valide.")
                elif key == "capacities":
                    if not isinstance(value,dict) or set(value)!=set(ROOMS) or any(type(v) is not int or not 1<=v<=4 for v in value.values()):
                        raise ApiError(400,"Capienze non valide.")
                elif key in ("booking_terms","bank_instructions","booking_terms_en","bank_instructions_en"):
                    if not isinstance(value,str) or len(value)>4000:
                        raise ApiError(400,"Condizioni troppo lunghe.")
                elif key == "rates":
                    if not isinstance(value, dict) or any(k not in ROOMS for k in value):
                        raise ApiError(400,"Tariffe non valide.")
                    if any(v is not None and (type(v) not in (int,float) or not 0 < v <= 10000) for v in value.values()):
                        raise ApiError(400,"Le tariffe devono essere positive, oppure vuote.")
                elif key == "smtp_port":
                    if type(value) is not int or not 1 <= value <= 65535:
                        raise ApiError(400,"Porta SMTP non valida.")
                elif not isinstance(value,str) or len(value)>2000 or "\n" in value or "\r" in value:
                    raise ApiError(400,"Valore non valido: "+key)
                elif key.endswith("_url") and value and not value.startswith("https://"):
                    raise ApiError(400,"Usare URL completi HTTPS.")
                elif key in ("email","smtp_from") and value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):
                    raise ApiError(400,"Indirizzo email non valido.")
                elif key == "smtp_mode" and value not in ("ssl","starttls"):
                    raise ApiError(400,"Selezionare TLS o SSL.")
                elif key == "stripe_secret" and value and not value.startswith(("sk_test_","sk_live_")):
                    raise ApiError(400,"Chiave Stripe non valida.")
                updates[key] = value
            merged = {**conf,**updates}
            if merged["direct_enabled"]:
                if not merged["payment_methods"] or not merged["booking_terms"].strip() or not any(merged["rates"].values()):
                    raise ApiError(400,"Per attivare le prenotazioni: impostare almeno una tariffa, un pagamento e le condizioni complete.")
                if "card" in merged["payment_methods"] and not all(merged[k] for k in ("stripe_secret","stripe_webhook_secret","site_url")):
                    raise ApiError(400,"Per la carta configurare Stripe, webhook e dominio HTTPS.")
                if "bank" in merged["payment_methods"] and not all(merged[k].strip() for k in ("bank_iban","bank_holder","bank_instructions")):
                    raise ApiError(400,"Per il bonifico inserire IBAN, intestatario e istruzioni/scadenza.")
            new_password = p.get("new_password","")
            if new_password:
                if not isinstance(new_password,str) or not 12 <= len(new_password) <= 128:
                    raise ApiError(400,"La nuova password deve contenere almeno 12 caratteri.")
                current = text_value(p,"current_password",500,True)
                if not hmac.compare_digest(password_hash(current,conf["password_salt"]),conf["password_hash"]):
                    raise ApiError(403,"Password attuale errata.")
                salt = secrets.token_hex(16)
                updates.update(password_salt=salt,password_hash=password_hash(new_password,salt))
            with db() as conn:
                for key,value in updates.items():
                    conn.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(value),key))
                if new_password:
                    conn.execute("DELETE FROM sessions")
                audit(conn,None,"Impostazioni aggiornate: "+", ".join(updates.keys()))
            conf = settings()
        elif method != "GET":
            raise ApiError(405,"Metodo non consentito.")
        output = {key:conf[key] for key in DEFAULTS if key not in SECRETS}
        output["configured"] = {key:bool(conf[key]) for key in SECRETS}
        output["storage"] = "PostgreSQL persistente" if DATABASE_URL else "SQLite locale"
        output["payment_mode"] = "live" if conf["stripe_secret"].startswith("sk_live_") else ("test" if conf["stripe_secret"] else "non configurato")
        return self.response(200,output)
    def manage_channels(self, path, method):
        if path == "/api/admin/channels" and method == "GET":
            return self.response(200,channels_state())
        match = re.fullmatch(r"/api/admin/channels/(suite-max|michele|rosa-e-romeo)/(booking|airbnb)",path)
        if match and method == "PATCH":
            room,channel = ROOM_SLUGS[match.group(1)],match.group(2)
            p = self.payload()
            listing = text_value(p,"listing_id",120)
            incoming = text_value(p,"import_url",2048)
            if p.get("clear_import",False) not in (True,False):
                raise ApiError(400,"Richiesta non valida.")
            if p.get("clear_import") and incoming:
                raise ApiError(400,"Scegliere se sostituire o rimuovere il calendario.")
            if incoming:
                incoming = validate_channel_url(incoming,channel)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM channel_connections WHERE apartment=? AND channel=?",(room,channel)).fetchone()
                if type(p.get("version")) is not int or p["version"] != row["version"]:
                    raise ApiError(409,"Configurazione modificata: ricaricare i collegamenti prima di salvare.")
                feed = "" if p.get("clear_import") else incoming or row["import_url"]
                if feed and conn.execute("SELECT 1 FROM channel_connections WHERE import_url=? AND apartment!=?",(feed,room)).fetchone():
                    raise ApiError(409,"Questo calendario e' gia' associato a un altro appartamento.")
                conn.execute("UPDATE channel_connections SET listing_id=?,import_url=?,updated_at=?,version=version+1 WHERE apartment=? AND channel=?",(listing,feed,now(),room,channel))
                audit(conn,None,"Predisposizione portale aggiornata: "+channel+" / "+room)
            return self.response(200,channels_state())
        if path == "/api/admin/channels/manager" and method == "PATCH":
            p = self.payload()
            provider = text_value(p,"provider",100)
            account = text_value(p,"account_ref",120)
            mappings = p.get("mappings")
            if not isinstance(mappings,dict) or set(mappings)!=set(ROOMS) or any(not isinstance(v,str) or len(v)>120 or any(ord(c)<32 for c in v) for v in mappings.values()):
                raise ApiError(400,"Controllare gli ID alloggio del channel manager.")
            clean = {room:mappings[room].strip() for room in ROOMS}
            ids = [v for v in clean.values() if v]
            if len(ids)!=len(set(ids)):
                raise ApiError(400,"Gli ID delle tre unita' devono essere distinti.")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                previous = channel_manager_config(conn)
                if type(p.get("version")) is not int or p["version"]!=previous["version"]:
                    raise ApiError(409,"Configurazione modificata: ricaricare i collegamenti prima di salvare.")
                value = {"provider":provider,"account_ref":account,"mappings":clean,"version":previous["version"]+1}
                conn.execute("INSERT INTO settings VALUES ('channel_manager_draft',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value),))
                audit(conn,None,"Predisposizione channel manager aggiornata; API non attiva")
            return self.response(200,channels_state())
        match = re.fullmatch(r"/api/admin/channels/exports/(suite-max|michele|rosa-e-romeo)",path)
        if match and method == "POST":
            p,room = self.payload(),ROOM_SLUGS[match.group(1)]
            action = p.get("action")
            if action not in ("create","rotate","revoke"):
                raise ApiError(400,"Operazione calendario non valida.")
            if action!="revoke" and not settings()["site_url"].startswith("https://"):
                raise ApiError(400,"Configurare il dominio HTTPS in Impostazioni prima di creare il link.")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT token FROM calendar_exports WHERE apartment=?",(room,)).fetchone()
                if action=="revoke":
                    conn.execute("DELETE FROM calendar_exports WHERE apartment=?",(room,))
                elif action=="rotate" or not existing:
                    conn.execute("INSERT INTO calendar_exports VALUES (?,?,?) ON CONFLICT(apartment) DO UPDATE SET token=excluded.token,updated_at=excluded.updated_at",(room,secrets.token_urlsafe(32),now()))
                audit(conn,None,"Link export calendario: "+action+" / "+room)
            return self.response(200,channels_state())
        raise ApiError(405,"Operazione canali non consentita.")

    def manage_booking(self, bid, action, method):
        if action == "events" and method == "GET":
            with db() as conn:
                return self.response(200,{"events":[dict(r) for r in conn.execute("SELECT action,created_at FROM events WHERE booking_id=? ORDER BY id DESC",(bid,))]})
        if not action and method == "PATCH":
            p = self.payload()
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = booking(conn,bid)
                desired = p.get("status",row["status"])
                allowed = ("blocked","cancelled") if row["id"].startswith("BL-") else ("pending","confirmed","declined","cancelled")
                if desired not in allowed:
                    raise ApiError(400,"Stato non valido.")
                room = p.get("apartment",row["apartment"])
                if room not in ROOMS and not (room=="Tutti gli appartamenti" and desired=="pending"):
                    raise ApiError(400,"Assegnare un appartamento prima di confermare.")
                amount = p.get("amount_cents",row["amount_cents"])
                if amount is not None and (type(amount) is not int or not 0 <= amount <= 10000000):
                    raise ApiError(400,"Importo non valido.")
                arrival=p.get("checkin",row["checkin"])
                departure=p.get("checkout",row["checkout"])
                validate_stay({"apartment":room if room in ROOMS else "Suite Max","checkin":arrival,"checkout":departure,"guests":row["guests"]},True)
                if (row["checkout_id"] or row["paid_at"]) and (amount!=row["amount_cents"] or desired!=row["status"] or room!=row["apartment"] or arrival!=row["checkin"] or departure!=row["checkout"]):
                    raise ApiError(409,"Esiste un pagamento collegato: gestire annullamento o rimborso in Stripe prima di modificare la prenotazione. Le note restano modificabili.")
                if desired in ("confirmed","blocked") and overlap(conn,room,arrival,departure,bid):
                    raise ApiError(409,"Date occupate: impossibile confermare una sovrapposizione.")
                notes = text_value(p,"notes",4000) if "notes" in p else row["notes"]
                conn.execute("UPDATE bookings SET status=?,apartment=?,amount_cents=?,notes=?,checkin=?,checkout=?,updated_at=? WHERE id=?", (desired,room,amount,notes,arrival,departure,now(),bid))
                audit(conn,bid,"Aggiornamento: "+desired)
            return self.response(200,{"ok":True})
        with db() as conn:
            row = booking(conn,bid)
        if action=="record-payment" and method=="POST":
            p = self.payload()
            reference = text_value(p,"reference",200,True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = booking(conn,bid)
                detail = conn.execute("SELECT method FROM direct_details WHERE booking_id=?",(bid,)).fetchone()
                if row["checkout_id"] or row["status"]!="confirmed" or not row["amount_cents"] or not detail or detail["method"] not in ("arrival","bank"):
                    raise ApiError(409,"Registrazione manuale ammessa solo per bonifico o pagamento all'arrivo confermati.")
                if not row["paid_at"]:
                    conn.execute("UPDATE bookings SET paid_at=?,payment_id=? WHERE id=?",(now(),"manual:"+reference,bid))
                    audit(conn,bid,"Incasso verificato manualmente dal proprietario: "+reference)
            return self.response(200,{"message":"Incasso registrato dal proprietario."})
        if action in ("sync-payment","expire-payment") and method=="POST":
            if not row["checkout_id"]:
                raise ApiError(409,"Nessuna sessione Stripe collegata.")
            current=stripe_request("checkout/sessions/"+row["checkout_id"])
            if current.get("payment_status")=="paid":
                if current.get("amount_total")!=row["amount_cents"] or current.get("currency")!="eur" or current.get("client_reference_id")!=bid:
                    raise ApiError(409,"Il pagamento non corrisponde alla prenotazione.")
                with db() as conn:
                    conn.execute("UPDATE bookings SET paid_at=?,payment_id=? WHERE id=?",(row["paid_at"] or now(),current.get("payment_intent"),bid))
                    audit(conn,bid,"Pagamento verificato tramite API Stripe")
                return self.response(200,{"message":"Pagamento verificato. Per eventuali rimborsi utilizzare la dashboard Stripe."})
            if action=="expire-payment" and current.get("status")=="open":
                current=stripe_request("checkout/sessions/"+row["checkout_id"]+"/expire",{},key="expire-"+row["checkout_id"])
            if current.get("status")=="expired":
                with db() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("UPDATE bookings SET checkout_id=NULL,checkout_url=NULL WHERE id=? AND paid_at IS NULL",(bid,))
                    if conn.execute("SELECT 1 FROM direct_details WHERE booking_id=? AND method='card'",(bid,)).fetchone():
                        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND paid_at IS NULL",(bid,))
                    conn.execute("INSERT INTO checkout_attempts VALUES (?,1) ON CONFLICT(booking_id) DO UPDATE SET generation=checkout_attempts.generation+1",(bid,))
                    audit(conn,bid,"Sessione Stripe scaduta; prenotazione nuovamente modificabile")
                return self.response(200,{"message":"Link scaduto o disattivato. È possibile modificare la prenotazione."})
            return self.response(200,{"message":"Pagamento non ancora completato."})
        if action=="invoice" and method=="GET":
            if not row["invoice_file"]:
                raise ApiError(404,"Nessun documento caricato.")
            data=base64.b64decode(row["invoice_file"])
            self.send_response(200)
            self.send_header("Content-Type","application/pdf")
            self.send_header("Content-Disposition",'attachment; filename="'+row["invoice_name"]+'"')
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            return self.wfile.write(data)
        if action=="invoice" and method=="POST":
            p=self.payload()
            name=text_value(p,"filename",150,True)
            name=re.sub(r"[^A-Za-z0-9_.-]","_",name)
            try:
                pdf=base64.b64decode(p.get("pdf",""),validate=True)
            except (ValueError,TypeError):
                raise ApiError(400,"PDF non valido.")
            if not name.lower().endswith(".pdf") or not pdf.startswith(b"%PDF-") or not 20<len(pdf)<=2*1024*1024:
                raise ApiError(400,"Caricare un PDF valido, massimo 2 MB.")
            with db() as conn:
                conn.execute("UPDATE bookings SET invoice_file=?,invoice_name=?,invoice_sent_at=NULL,email_error=NULL,updated_at=? WHERE id=?", (base64.b64encode(pdf).decode(),name,now(),bid))
                audit(conn,bid,"PDF di cortesia caricato: "+name)
            return self.response(200,{"ok":True})
        if action=="checkout" and method=="POST":
            if row["status"]!="confirmed" or not row["amount_cents"] or row["paid_at"]:
                raise ApiError(409,"Confermare la prenotazione e impostare un importo positivo prima del pagamento.")
            conf=settings()
            if not conf["site_url"] or not conf["stripe_webhook_secret"]:
                raise ApiError(503,"Configurare dominio HTTPS e segreto webhook Stripe in Impostazioni.")
            if row["checkout_id"] and row["checkout_id"] != "creating":
                existing=stripe_request("checkout/sessions/"+row["checkout_id"])
                if existing.get("status")=="open":
                    return self.response(200,{"url":row["checkout_url"]})
                raise ApiError(409,"La sessione Stripe è conclusa o scaduta. Verificare il pagamento nella dashboard Stripe.")
            # Lock the quote before contacting Stripe; retries reuse the same immutable amount.
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                locked=booking(conn,bid)
                if locked["amount_cents"]!=row["amount_cents"] or locked["status"]!="confirmed":
                    raise ApiError(409,"Prenotazione modificata. Aggiornare prima di creare il pagamento.")
                if locked["checkout_id"] and locked["checkout_id"]!="creating":
                    return self.response(200,{"url":locked["checkout_url"]})
                conn.execute("UPDATE bookings SET checkout_id='creating' WHERE id=?",(bid,))
            with db() as conn:
                generation=conn.execute("SELECT generation FROM checkout_attempts WHERE booking_id=?",(bid,)).fetchone()
            generation=generation["generation"] if generation else 0
            language = booking_language(bid)
            payment_path = "/en/payment.html" if language == "en" else "/pagamento.html"
            result=stripe_request("checkout/sessions", {
                "mode":"payment","client_reference_id":bid,"customer_email":row["email"],"locale":language,
                "line_items[0][price_data][currency]":"eur",
                "line_items[0][price_data][unit_amount]":row["amount_cents"],
                "line_items[0][price_data][product_data][name]":"Dai Squee - "+row["apartment"],
                "line_items[0][price_data][product_data][description]":row["checkin"]+" / "+row["checkout"],
                "line_items[0][quantity]":1,"metadata[booking_id]":bid,
                "payment_intent_data[metadata][booking_id]":bid,
                "success_url":conf["site_url"].rstrip("/")+payment_path+"?esito=ritorno",
                "cancel_url":conf["site_url"].rstrip("/")+payment_path+"?esito=annullato"
            },key="checkout-"+bid+"-"+str(row["amount_cents"])+"-"+str(generation))
            with db() as conn:
                conn.execute("UPDATE bookings SET checkout_id=?,checkout_url=?,updated_at=? WHERE id=?", (result["id"],result["url"],now(),bid))
                audit(conn,bid,"Link di pagamento Stripe creato")
            return self.response(200,{"url":result["url"]})
        if action in ("send-invoice","send-payment","send-confirmation") and method=="POST":
            conf=settings()
            attachment=None
            if action=="send-invoice":
                if not row["invoice_file"]:
                    raise ApiError(409,"Caricare prima il PDF.")
                subject="Dai Squee - copia di cortesia "+bid
                content="Gentile "+row["name"]+",\n\nin allegato la copia di cortesia del documento relativo al soggiorno "+bid+".\n\n"+conf["business_name"]
                attachment=(row["invoice_name"],base64.b64decode(row["invoice_file"]))
            elif action=="send-payment":
                if not row["checkout_url"] or row["paid_at"] or row["status"]!="confirmed":
                    raise ApiError(409,"Non è disponibile un link di pagamento da inviare.")
                subject="Dai Squee - pagamento soggiorno "+bid
                content="Gentile "+row["name"]+",\n\nper il soggiorno "+row["checkin"]+" / "+row["checkout"]+" in "+row["apartment"]+", l'importo concordato è EUR "+format(row["amount_cents"]/100,".2f")+".\n\nPagamento sicuro: "+row["checkout_url"]+"\n\n"+conf["business_name"]
            else:
                if row["status"]!="confirmed":
                    raise ApiError(409,"Confermare prima la prenotazione.")
                with db() as conn:
                    direct = conn.execute("SELECT method FROM direct_details WHERE booking_id=?",(bid,)).fetchone()
                if direct and direct["method"]=="card" and not row["paid_at"]:
                    raise ApiError(409,"La prenotazione con carta attende un pagamento verificato.")
                subject="Dai Squee - conferma soggiorno "+bid
                content="Gentile "+row["name"]+",\n\nconfermiamo il soggiorno in "+row["apartment"]+" dal "+row["checkin"]+" al "+row["checkout"]+" per "+str(row["guests"])+" ospiti.\n\nPer orario di arrivo e informazioni: "+conf["phone"]+".\n\n"+conf["business_name"]
            if booking_language(bid) == "en":
                greeting = "Dear "+row["name"]+",\n\n"
                if action == "send-invoice":
                    subject = "Dai Squee - courtesy copy "+bid
                    content = greeting+"Please find attached a courtesy copy of the document for your stay "+bid+".\n\n"+conf["business_name"]
                elif action == "send-payment":
                    subject = "Dai Squee - payment for your stay "+bid
                    content = greeting+"For your stay "+row["checkin"]+" / "+row["checkout"]+" in "+row["apartment"]+", the agreed total is EUR "+format(row["amount_cents"]/100,".2f")+".\n\nSecure payment: "+row["checkout_url"]+"\n\n"+conf["business_name"]
                else:
                    subject = "Dai Squee - stay confirmation "+bid
                    content = greeting+"Your stay in "+row["apartment"]+" from "+row["checkin"]+" to "+row["checkout"]+" for "+str(row["guests"])+" guests is confirmed.\n\nFor arrival arrangements and information: "+conf["phone"]+".\n\n"+conf["business_name"]
            try:
                send_mail(row["email"],subject,content,attachment)
            except ApiError as error:
                with db() as conn:
                    conn.execute("UPDATE bookings SET email_error=? WHERE id=?",(error.message,bid))
                    audit(conn,bid,"Invio email fallito o incerto: "+action)
                raise
            with db() as conn:
                column="invoice_sent_at" if action=="send-invoice" else "payment_email_at"
                if action!="send-confirmation":
                    conn.execute("UPDATE bookings SET "+column+"=?,email_error=NULL WHERE id=?",(now(),bid))
                audit(conn,bid,"Email accettata dal server SMTP: "+action)
            return self.response(200,{"message":"Email accettata dal server SMTP. La consegna finale dipende dal server destinatario."})
        raise ApiError(405,"Operazione non consentita.")
    def webhook(self):
        raw=self.raw_body(1024*1024)
        conf=settings()
        secret=conf["stripe_webhook_secret"]
        if not secret:
            raise ApiError(503,"Webhook non configurato.")
        parts={}
        for segment in self.headers.get("Stripe-Signature","").split(","):
            key,_,value=segment.partition("=")
            parts.setdefault(key,[]).append(value)
        try:
            timestamp=int(parts["t"][0])
        except (KeyError,ValueError):
            raise ApiError(400,"Firma non valida.")
        signature=hmac.new(secret.encode(),str(timestamp).encode()+b"."+raw,hashlib.sha256).hexdigest()
        if abs(time.time()-timestamp)>300 or not any(hmac.compare_digest(signature,s) for s in parts.get("v1",[])):
            raise ApiError(400,"Firma non valida.")
        try:
            event=json.loads(raw)
            event_id=event["id"]
            obj=event["data"]["object"]
        except (ValueError,KeyError,TypeError):
            raise ApiError(400,"Evento non valido.")
        notify_bid = None
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM stripe_events WHERE id=?",(event_id,)).fetchone():
                return self.response(200,{"received":True})
            if event.get("type") in ("checkout.session.completed","checkout.session.async_payment_succeeded"):
                bid=obj.get("client_reference_id")
                if bid:
                    row=booking(conn,bid)
                    if obj.get("id")!=row["checkout_id"]:
                        raise ApiError(409,"Sessione di pagamento non corrispondente.")
                    if obj.get("payment_status")=="paid":
                        if obj.get("amount_total")!=row["amount_cents"] or obj.get("currency")!="eur":
                            raise ApiError(409,"Importo di pagamento non corrispondente.")
                        conn.execute("UPDATE bookings SET paid_at=?,payment_id=?,updated_at=? WHERE id=?", (row["paid_at"] or now(),obj.get("payment_intent"),now(),bid))
                        audit(conn,bid,"Pagamento verificato tramite webhook Stripe")
                        notify_bid = bid
            if event.get("type")=="checkout.session.expired" and obj.get("client_reference_id"):
                bid = obj["client_reference_id"]
                row = booking(conn,bid)
                direct = conn.execute("SELECT 1 FROM direct_details WHERE booking_id=? AND method='card'",(bid,)).fetchone()
                if direct and row["checkout_id"]==obj.get("id") and not row["paid_at"] and obj.get("status")=="expired":
                    conn.execute("UPDATE bookings SET status='cancelled',updated_at=? WHERE id=?",(now(),bid))
                    audit(conn,bid,"Checkout scaduto: date nuovamente disponibili")
            conn.execute("INSERT INTO stripe_events VALUES (?,?)",(event_id,now()))
        if notify_bid:
            direct_email(notify_bid)
        return self.response(200,{"received":True})

if __name__=="__main__":
    init()
    port=int(os.environ.get("PORT","8787"))
    print("Dai Squee: http://127.0.0.1:"+str(port),flush=True)
    ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
