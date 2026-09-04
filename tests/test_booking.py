import base64
from datetime import date, timedelta
import hashlib
import hmac
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server

class BookingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DATA = Path(cls.temp.name)
        server.DATABASE_URL = ""
        server.INITIALIZED = False
        server.init()
        cls.http = ThreadingHTTPServer(("127.0.0.1",0),server.Handler)
        cls.base = "http://127.0.0.1:"+str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.password = (server.DATA/"admin-access.txt").read_text().split("Password: ")[1].splitlines()[0]
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()
    def setUp(self):
        with server.db() as conn:
            for table in ("bookings","direct_details","apartment_photos","photo_translations","booking_languages","events","stripe_events","sessions","rate_limits"):
                conn.execute("DELETE FROM "+table)
            for key,value in server.DEFAULTS.items():
                conn.execute("UPDATE settings SET value=? WHERE key=?",(json.dumps(value),key))
        self.cookie = ""
        self.csrf = ""
    def call(self,path,method="GET",payload=None,headers=None):
        hdr={"Content-Type":"application/json"}
        if self.cookie:
            hdr["Cookie"]=self.cookie
            hdr["X-CSRF-Token"]=self.csrf
        hdr.update(headers or {})
        raw=payload if isinstance(payload,bytes) else json.dumps(payload).encode() if payload is not None else None
        try:
            response=urlopen(Request(self.base+path,data=raw,method=method,headers=hdr),timeout=10)
        except HTTPError as error:
            response=error
        body=response.read()
        return response.status, json.loads(body) if response.headers.get("Content-Type","").startswith("application/json") else body, response.headers
    def login(self):
        code,p,hdr=self.call("/api/admin/login","POST",{"username":"admin","password":self.password})
        self.assertEqual(code,200)
        self.cookie=hdr["Set-Cookie"].split(";")[0]
        self.csrf=p["csrf"]
    def create(self,key="test-request-001",room="Suite Max"):
        arrival=date.today()+timedelta(days=20)
        return self.call("/api/bookings","POST",{"name":"Test Guest","email":"test@example.invalid","phone":"","apartment":room,"checkin":arrival.isoformat(),"checkout":(arrival+timedelta(days=3)).isoformat(),"guests":2,"channel":"Diretto","message":"Test","consent":True},{"Idempotency-Key":key})
    def test_authentication_and_private_files(self):
        self.assertEqual(self.call("/api/admin/bookings")[0],401)
        self.assertEqual(self.call("/.local-data/admin-access.txt")[0],404)
        self.assertEqual(self.call("/server.py")[0],404)
        self.login()
        self.assertEqual(self.call("/api/admin/settings","PATCH",{"business_name":"Test"},{"X-CSRF-Token":"wrong"})[0],403)
        self.assertEqual(self.call("/api/admin/settings","PATCH",{},{"Origin":"https://attacker.invalid"})[0],403)
    def test_request_idempotency_and_conflicts(self):
        code,first,_=self.create()
        self.assertEqual(code,201)
        code,second,_=self.create()
        self.assertEqual(first,second)
        self.login()
        path="/api/admin/bookings/"+first["reference"]
        self.assertEqual(self.call(path,"PATCH",{"status":"confirmed","amount_cents":30000})[0],200)
        self.assertEqual(self.create("test-request-002")[0],409)
        self.assertEqual(self.create("test-request-003","Michele")[0],201)
    def test_invalid_dates_and_capacity(self):
        code,_,_=self.call("/api/bookings","POST",{"name":"X","email":"x@example.invalid","apartment":"Suite Max","checkin":"2020-01-01","checkout":"2020-01-02","guests":5,"consent":True},{"Idempotency-Key":"invalid-request"})
        self.assertEqual(code,400)
    def test_pdf_private_storage_and_email_errors(self):
        _,p,_=self.create()
        self.login()
        path="/api/admin/bookings/"+p["reference"]
        self.assertEqual(self.call(path+"/invoice","POST",{"filename":"bad.pdf","pdf":base64.b64encode(b"not a pdf").decode()})[0],400)
        pdf=b"%PDF-1.4\nA test PDF body\n%%EOF"
        self.assertEqual(self.call(path+"/invoice","POST",{"filename":"invoice.pdf","pdf":base64.b64encode(pdf).decode()})[0],200)
        self.assertEqual(self.call(path+"/invoice")[1],pdf)
        rows=self.call("/api/admin/bookings")[1]["bookings"]
        self.assertNotIn("invoice_file",rows[0])
        self.assertTrue(rows[0]["has_invoice"])
        with patch("server.send_mail",side_effect=server.ApiError(503,"SMTP non configurato")):
            self.assertEqual(self.call(path+"/send-invoice","POST",{})[0],503)
        with server.db() as conn:
            self.assertIsNone(server.booking(conn,p["reference"])["invoice_sent_at"])
        with patch("server.send_mail") as mail:
            self.assertEqual(self.call(path+"/send-invoice","POST",{})[0],200)
            self.assertEqual(mail.call_args.args[0],"test@example.invalid")
        self.cookie=""
        self.assertEqual(self.call(path+"/invoice")[0],401)
    def test_secrets_are_not_returned(self):
        self.login()
        self.assertEqual(self.call("/api/admin/settings","PATCH",{"stripe_secret":"sk_test_private","smtp_password":"privatepass"})[0],200)
        settings=self.call("/api/admin/settings")[1]
        self.assertNotIn("stripe_secret",settings)
        self.assertNotIn("smtp_password",settings)
        self.assertTrue(settings["configured"]["stripe_secret"])
    def test_photo_management_requires_admin(self):
        payload={"apartment":"Suite Max","role":"cover","caption":"Terrazzo","image":base64.b64encode(b"\xff\xd8\xff"+b"0"*200).decode()}
        self.assertEqual(self.call("/api/admin/photos","POST",payload)[0],401)
        self.login()
        code,result,_=self.call("/api/admin/photos","POST",payload)
        self.assertEqual(code,201)
        self.assertEqual(self.call("/api/photos/"+result["id"])[2]["Content-Type"],"image/jpeg")
        public=self.call("/api/apartment-photos")[1]["photos"]
        self.assertNotIn("data",public[0])
        self.assertEqual(self.call("/api/admin/photos/"+result["id"],"PATCH",{"caption":"Vista"})[0],200)
        self.assertEqual(self.call("/api/admin/photos/"+result["id"],"PATCH",{"remove":True})[0],200)
        self.assertEqual(self.call("/api/photos/"+result["id"])[0],404)
        payload["image"]=base64.b64encode(b"<svg>not allowed</svg>").decode()
        self.assertEqual(self.call("/api/admin/photos","POST",payload)[0],400)
    def test_confirmation_conflict_atomic(self):
        _,a,_=self.create("overlap-one")
        _,b,_=self.create("overlap-two")
        self.login()
        self.assertEqual(self.call("/api/admin/bookings/"+a["reference"],"PATCH",{"status":"confirmed"})[0],200)
        self.assertEqual(self.call("/api/admin/bookings/"+b["reference"],"PATCH",{"status":"confirmed"})[0],409)
    def configure_direct(self, methods=None):
        self.login()
        values={"direct_enabled":True,"rates":{r:100 for r in server.ROOMS},"payment_methods":methods or ["arrival"],"booking_terms":"Test conditions; all mandatory costs included.","bank_iban":"IT60X0542811101000000123456","bank_holder":"Test","bank_instructions":"Test bank deadline","stripe_secret":"sk_test_mock","stripe_webhook_secret":"whsec_test","site_url":"https://example.invalid"}
        self.assertEqual(self.call("/api/admin/settings","PATCH",values)[0],200)
    def quote(self,room="Suite Max"):
        arrival=date.today()+timedelta(days=20)
        stay={"apartment":room,"checkin":arrival.isoformat(),"checkout":(arrival+timedelta(days=3)).isoformat(),"guests":2}
        code,result,_=self.call("/api/quote","POST",stay)
        self.assertEqual(code,200)
        return {**stay,"expires":result["expires"],"signature":result["signature"],"name":"Direct Test","email":"test@example.invalid","consent":True,"terms_consent":True,"payment_method":"arrival"}
    def test_calendar_changes_follow_admin(self):
        _,r,_=self.create()
        self.assertEqual(self.call("/api/availability")[1]["unavailable"],[])
        self.login()
        path="/api/admin/bookings/"+r["reference"]
        self.assertEqual(self.call(path,"PATCH",{"status":"confirmed"})[0],200)
        rows=self.call("/api/availability")[1]["unavailable"]
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]),{"apartment","checkin","checkout"})
        shifted=(date.today()+timedelta(days=25)).isoformat()
        self.assertEqual(self.call(path,"PATCH",{"checkout":shifted})[0],200)
        self.assertEqual(self.call("/api/availability")[1]["unavailable"][0]["checkout"],shifted)
        self.assertEqual(self.call(path,"PATCH",{"status":"cancelled"})[0],200)
        self.assertEqual(self.call("/api/availability")[1]["unavailable"],[])
    def test_direct_arrival_quote_integrity_and_idempotency(self):
        self.configure_direct()
        payload=self.quote()
        bad={**payload,"checkout":(date.today()+timedelta(days=24)).isoformat()}
        self.assertEqual(self.call("/api/reserve","POST",bad,{"Idempotency-Key":"direct-test-idempotency-0001"})[0],409)
        payload["amount_cents"]=1
        with patch("server.send_mail"):
            code,r,_=self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-idempotency-0001"})
            self.assertEqual(code,200)
            self.assertEqual(r["amount_cents"],30000)
            self.assertEqual(r["status"],"confirmed")
            self.assertFalse(r["paid"])
            self.assertEqual(self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-idempotency-0001"})[1]["reference"],r["reference"])
        self.assertEqual(self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-idempotency-0002"})[0],409)
        self.assertEqual(self.call("/api/reservation?token="+r["access_token"])[0],200)
        self.assertEqual(self.call("/api/reservation?token=bad")[0],404)
        self.assertEqual(self.call("/api/admin/bookings/"+r["reference"],"PATCH",{"status":"cancelled"})[0],200)
    def test_direct_disabled_and_methods(self):
        self.assertEqual(self.call("/api/admin/settings","PATCH",{})[0],401)
        self.configure_direct()
        payload=self.quote()
        payload["payment_method"]="card"
        self.assertEqual(self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-payment-00001"})[0],400)
        payload["payment_method"]="arrival"
        self.assertEqual(self.call("/api/admin/settings","PATCH",{"direct_enabled":False})[0],200)
        self.assertEqual(self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-payment-00001"})[0],503)
    def test_bank_manual_payment(self):
        self.configure_direct(["bank"])
        payload=self.quote();payload["payment_method"]="bank"
        with patch("server.send_mail"):
            code,r,_=self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-bank-00001"})
        self.assertEqual(code,200)
        self.assertFalse(r["paid"])
        path="/api/admin/bookings/"+r["reference"]
        self.assertEqual(self.call(path+"/record-payment","POST",{"reference":"TRN-test"})[0],200)
        self.assertTrue(self.call("/api/reservation?token="+r["access_token"])[1]["paid"])
        self.assertEqual(self.call(path,"PATCH",{"amount_cents":1})[0],409)
    def test_card_expiration_releases_dates_only_after_signed_webhook(self):
        self.configure_direct(["card"])
        payload=self.quote();payload["payment_method"]="card"
        with patch("server.stripe_request",return_value={"id":"cs_direct","url":"https://checkout.stripe.com/test"}) as stripe:
            code,r,_=self.call("/api/reserve","POST",payload,{"Idempotency-Key":"direct-test-card-00001"})
            self.assertEqual(code,200)
            self.assertEqual(stripe.call_args.args[1]["payment_method_types[0]"],"card")
        self.assertFalse(r["paid"])
        self.assertEqual(len(self.call("/api/availability")[1]["unavailable"]),1)
        event={"id":"evt_expired","type":"checkout.session.expired","data":{"object":{"id":"cs_direct","client_reference_id":r["reference"],"status":"expired"}}}
        self.assertEqual(self.call("/api/stripe/webhook","POST",event)[0],400)
        body=json.dumps(event).encode(); timestamp=str(int(time.time()))
        signature=hmac.new(b"whsec_test",timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
        self.assertEqual(self.call("/api/stripe/webhook","POST",body,{"Stripe-Signature":"t="+timestamp+",v1="+signature})[0],200)
        self.assertEqual(self.call("/api/availability")[1]["unavailable"],[])
    def test_stripe_signature_amount_and_duplicate_event(self):
        _,p,_=self.create()
        bid=p["reference"]
        with server.db() as conn:
            conn.execute("UPDATE settings SET value=? WHERE key='stripe_webhook_secret'",(json.dumps("whsec_test"),))
            conn.execute("UPDATE bookings SET status='confirmed',amount_cents=30000,checkout_id='cs_test' WHERE id=?",(bid,))
        event={"id":"evt_test","type":"checkout.session.completed","data":{"object":{"id":"cs_test","client_reference_id":bid,"payment_status":"paid","amount_total":1,"currency":"eur","payment_intent":"pi_test"}}}
        def signed(event):
            body=json.dumps(event).encode()
            timestamp=str(int(time.time()))
            signature=hmac.new(b"whsec_test",timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
            return self.call("/api/stripe/webhook","POST",body,{"Stripe-Signature":"t="+timestamp+",v1="+signature})
        self.assertEqual(self.call("/api/stripe/webhook","POST",event)[0],400)
        self.assertEqual(signed(event)[0],409)
        event["data"]["object"]["amount_total"]=30000
        self.assertEqual(signed(event)[0],200)
        self.assertEqual(signed(event)[0],200)
        with server.db() as conn:
            self.assertIsNotNone(server.booking(conn,bid)["paid_at"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0],1)

    def test_english_quote_terms_and_signature(self):
        self.configure_direct(["arrival","bank"])
        payload = self.quote()
        stay = {**payload,"language":"en"}
        code,result,_ = self.call("/api/quote","POST",stay,{"Accept-Language":"en"})
        self.assertEqual(code,503)
        self.assertIn("English booking terms",result["error"])
        self.assertEqual(self.call("/api/admin/settings","PATCH",{"booking_terms_en":"English conditions.\nCheck-in from 15:00."})[0],200)
        code,result,_ = self.call("/api/quote","POST",stay)
        self.assertEqual(code,200)
        self.assertEqual(result["quote"]["language"],"en")
        self.assertEqual(result["quote"]["methods"],["arrival"])
        self.assertIn("English conditions",result["quote"]["terms"])
        stay.update(expires=result["expires"],signature=result["signature"])
        wrong = {**stay,"language":"it"}
        self.assertEqual(self.call("/api/reserve","POST",wrong,{"Idempotency-Key":"english-tamper-0000000001"})[0],409)
        with patch("server.send_mail") as mail:
            code,reservation,_ = self.call("/api/reserve","POST",stay,{"Idempotency-Key":"english-booking-00000001"})
            self.assertEqual(code,200)
            self.assertIn("booking",mail.call_args.args[1])
            self.assertIn("Payment: on arrival",mail.call_args.args[2])
            self.assertEqual(server.booking_language(reservation["reference"]),"en")
        with patch("server.send_mail") as mail:
            self.call("/api/admin/bookings/"+reservation["reference"]+"/send-confirmation","POST",{})
            self.assertIn("stay confirmation",mail.call_args.args[1])

    def test_english_card_checkout_and_bank_instructions(self):
        self.configure_direct(["bank","card"])
        self.call("/api/admin/settings","PATCH",{"booking_terms_en":"English terms","bank_instructions_en":"Transfer within 48 hours"})
        stay = {**self.quote(),"language":"en","payment_method":"card"}
        _,quote,_ = self.call("/api/quote","POST",stay)
        self.assertEqual(quote["quote"]["bank_instructions"],"Transfer within 48 hours")
        stay.update(expires=quote["expires"],signature=quote["signature"])
        with patch("server.stripe_request",return_value={"id":"cs_english","url":"https://checkout.stripe.com/mock"}) as stripe:
            code,result,_ = self.call("/api/reserve","POST",stay,{"Idempotency-Key":"english-stripe-000000001"})
            self.assertEqual(code,200)
            params = stripe.call_args.args[1]
            self.assertEqual(params["locale"],"en")
            self.assertIn("/en/book.html?receipt=",params["success_url"])
            self.assertEqual(params["cancel_url"],params["success_url"])

    def test_english_error_and_pages(self):
        code,result,_ = self.call("/api/quote","POST",{},{"Accept-Language":"en-GB"})
        self.assertEqual(code,400)
        self.assertEqual(result["error"],"Please select an apartment.")
        self.assertEqual(self.call("/en/")[0],200)
        self.assertEqual(self.call("/en/about.html")[0],200)
        self.assertEqual(self.call("/translations/en.json")[0],404)
        self.assertEqual(self.call("/en/../server.py")[0],404)
        self.assertIn(b'lang="en"',self.call("/en/book.html")[1])

    def test_english_photo_caption(self):
        self.login()
        payload = {"apartment":"Michele","role":"cover","caption":"La camera","caption_en":"The bedroom","image":base64.b64encode(b"\xff\xd8\xff"+b"0"*200).decode()}
        code,result,_ = self.call("/api/admin/photos","POST",payload)
        self.assertEqual(code,201)
        self.assertEqual(self.call("/api/apartment-photos")[1]["photos"][0]["caption_en"],"The bedroom")
        self.call("/api/admin/photos/"+result["id"],"PATCH",{"caption_en":"The living room"})
        self.assertEqual(self.call("/api/apartment-photos")[1]["photos"][0]["caption_en"],"The living room")
        self.call("/api/admin/photos/"+result["id"],"PATCH",{"remove":True})
        with server.db() as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM photo_translations WHERE photo_id=?",(result["id"],)).fetchone())

if __name__=="__main__":
    unittest.main()
