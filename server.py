"""Dai Squee: static site, reservations, private administration and integrations."""
import base64
import hashlib
import hmac
import json
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
SECRETS = ("stripe_secret", "stripe_webhook_secret", "smtp_password")
DEFAULTS = {
    "business_name": "Dai Squee", "email": "info@daisquee.it", "phone": "+39 349 4454604",
    "address": "Viale A. Canova 51, 31054 Possagno (TV)", "site_url": ("https://"+os.environ["VERCEL_PROJECT_PRODUCTION_URL"]) if os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") else "",
    "stripe_secret": "", "stripe_webhook_secret": "", "smtp_host": "", "smtp_port": 587,
    "smtp_user": "", "smtp_password": "", "smtp_from": "", "smtp_mode": "starttls",
    "booking_url": "https://www.booking.com/", "airbnb_url": "https://www.airbnb.it/",
    "vrbo_url": "https://www.vrbo.com/", "rates": {room: None for room in ROOMS}
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
        """)
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
        self.handle_request()
    def do_POST(self):
        self.handle_request()
    def do_PATCH(self):
        self.handle_request()
    def handle_request(self):
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
        target = (ROOT / decoded).resolve()
        allowed = {".html", ".css", ".js", ".jpg", ".jpeg", ".png", ".webp", ".ico", ".svg", ".woff2"}
        if not target.is_relative_to(ROOT) or not target.is_file() or not (target.parent == ROOT or target.is_relative_to(ROOT / "assets")) or (target.suffix not in allowed and target.name not in ("robots.txt", "sitemap.xml", "llms.txt")):
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
        if path == "/api/health" and method == "GET":
            return self.response(200, {"ok": True})
        if path == "/api/config" and method == "GET":
            conf = settings()
            return self.response(200, {key: conf[key] for key in ("business_name","email","phone","address","booking_url","airbnb_url","vrbo_url")})
        if path == "/api/availability" and method == "GET":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT apartment,checkin,checkout FROM bookings WHERE status IN ('confirmed','blocked') AND checkout>=?", (date.today().isoformat(),))]
            return self.response(200, {"unavailable": rows})
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
            secure = "; Secure" if settings()["site_url"].startswith("https://") else ""
            return self.response(200, {"csrf":csrf}, "daisquee_session="+token+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"+secure)
        if path == "/api/stripe/webhook" and method == "POST":
            return self.webhook()
        if not path.startswith("/api/admin/"):
            raise ApiError(404, "Risorsa non trovata.")
        session = self.session(method != "GET")
        if path == "/api/admin/session" and method == "GET":
            return self.response(200, {"csrf":session["csrf"]})
        if path == "/api/admin/logout" and method == "POST":
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
            return self.response(200, {"ok":True}, "daisquee_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path == "/api/admin/settings":
            return self.manage_settings(method)
        if path == "/api/admin/test-email" and method == "POST":
            conf = settings()
            send_mail(conf["email"], "Dai Squee - verifica email", "La configurazione email di Dai Squee funziona.")
            return self.response(200, {"message":"Email di prova accettata dal server SMTP."})
        if path == "/api/admin/bookings" and method == "GET":
            with db() as conn:
                rows = []
                for row in conn.execute("SELECT * FROM bookings ORDER BY created_at DESC"):
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
        match = re.fullmatch(r"/api/admin/bookings/(DS-[A-F0-9]{8}|BL-[A-F0-9]{8})(?:/(events|checkout|invoice|send-invoice|send-payment|send-confirmation|sync-payment|expire-payment))?", path)
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
                if key == "rates":
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
                if row["checkout_id"] and (amount!=row["amount_cents"] or desired!=row["status"] or room!=row["apartment"] or arrival!=row["checkin"] or departure!=row["checkout"]):
                    raise ApiError(409,"Esiste un pagamento collegato: gestire annullamento o rimborso in Stripe prima di modificare la prenotazione. Le note restano modificabili.")
                if desired in ("confirmed","blocked") and overlap(conn,room,arrival,departure,bid):
                    raise ApiError(409,"Date occupate: impossibile confermare una sovrapposizione.")
                notes = text_value(p,"notes",4000) if "notes" in p else row["notes"]
                conn.execute("UPDATE bookings SET status=?,apartment=?,amount_cents=?,notes=?,checkin=?,checkout=?,updated_at=? WHERE id=?", (desired,room,amount,notes,arrival,departure,now(),bid))
                audit(conn,bid,"Aggiornamento: "+desired)
            return self.response(200,{"ok":True})
        with db() as conn:
            row = booking(conn,bid)
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
            result=stripe_request("checkout/sessions", {
                "mode":"payment","client_reference_id":bid,"customer_email":row["email"],
                "line_items[0][price_data][currency]":"eur",
                "line_items[0][price_data][unit_amount]":row["amount_cents"],
                "line_items[0][price_data][product_data][name]":"Dai Squee - "+row["apartment"],
                "line_items[0][price_data][product_data][description]":row["checkin"]+" / "+row["checkout"],
                "line_items[0][quantity]":1,"metadata[booking_id]":bid,
                "payment_intent_data[metadata][booking_id]":bid,
                "success_url":conf["site_url"].rstrip("/")+"/pagamento.html?esito=ritorno",
                "cancel_url":conf["site_url"].rstrip("/")+"/pagamento.html?esito=annullato"
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
                subject="Dai Squee - conferma soggiorno "+bid
                content="Gentile "+row["name"]+",\n\nconfermiamo il soggiorno in "+row["apartment"]+" dal "+row["checkin"]+" al "+row["checkout"]+" per "+str(row["guests"])+" ospiti.\n\nPer orario di arrivo e informazioni: "+conf["phone"]+".\n\n"+conf["business_name"]
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
            conn.execute("INSERT INTO stripe_events VALUES (?,?)",(event_id,now()))
        return self.response(200,{"received":True})

if __name__=="__main__":
    init()
    port=int(os.environ.get("PORT","8787"))
    print("Dai Squee: http://127.0.0.1:"+str(port),flush=True)
    ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
