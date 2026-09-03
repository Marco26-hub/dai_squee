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
            for table in ("bookings","events","stripe_events","sessions","rate_limits"):
                conn.execute("DELETE FROM "+table)
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
    def test_confirmation_conflict_atomic(self):
        _,a,_=self.create("overlap-one")
        _,b,_=self.create("overlap-two")
        self.login()
        self.assertEqual(self.call("/api/admin/bookings/"+a["reference"],"PATCH",{"status":"confirmed"})[0],200)
        self.assertEqual(self.call("/api/admin/bookings/"+b["reference"],"PATCH",{"status":"confirmed"})[0],409)
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

if __name__=="__main__":
    unittest.main()
