import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import auth
from dashboard.app import create_app
from src import dashboard_data
import test_dashboard as td

PW = "correct horse battery staple"
ORIGIN = {"Origin": "http://localhost"}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class RemoteAuthTests(unittest.TestCase):
    def setUp(self):
        reports = tempfile.mkdtemp()
        dashboard_data.write_latest(td.sample_payload(), os.path.join(reports, "latest.json"))
        self.clock = Clock()
        self.app = create_app(reports, tempfile.mkdtemp(), run_cmd=[sys.executable, "-c", "pass"],
                              auth_options={"password_hash": auth.hash_password(PW), "secret_key": "test",
                                            "require_login": True, "https": False, "clock": self.clock})
        self.c = self.app.test_client()

    def login(self, pw=PW, **kw):
        return self.c.post("/login", data={"password": pw, "remember": "on"}, headers=ORIGIN, **kw)

    def test_everything_needs_login(self):
        for path in ["/", "/portfolio", "/sell", "/cash", "/stock/NVDA", "/history"]:
            r = self.c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers["Location"])
        self.assertEqual(self.c.get("/api/latest").status_code, 401)
        self.assertEqual(self.c.post("/refresh", headers=ORIGIN).status_code, 401)
        self.assertEqual(self.c.get("/health").status_code, 200)
        self.assertEqual(self.c.get("/static/style.css").status_code, 200)

    def test_login_logout(self):
        self.assertIn("Wrong password", self.login("nope").get_data(as_text=True))
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertIn("NVIDIA", self.c.get("/stock/NVDA").get_data(as_text=True))
        self.assertIn("Log out", self.c.get("/").get_data(as_text=True))
        self.assertEqual(self.c.get("/api/latest").status_code, 200)
        self.c.post("/logout", headers=ORIGIN)
        self.assertEqual(self.c.get("/").status_code, 302)

    def test_next_redirect_stays_on_site(self):
        r = self.c.post("/login?next=/cash", data={"password": PW}, headers=ORIGIN)
        self.assertTrue(r.headers["Location"].endswith("/cash"))
        self.c.post("/logout", headers=ORIGIN)
        r = self.c.post("/login?next=//evil.example/x", data={"password": PW}, headers=ORIGIN)
        self.assertNotIn("evil", r.headers["Location"])

    def test_cross_site_login_blocked(self):
        r = self.c.post("/login", data={"password": PW}, headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_lockout_after_failures_even_with_right_password(self):
        for _ in range(auth.MAX_FAILURES):
            self.login("wrong")
        r = self.login()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Too many attempts", r.get_data(as_text=True))
        self.clock.t += auth.LOCKOUT + 1
        self.assertEqual(self.login().status_code, 302)

    def test_global_lockout_across_addresses(self):
        for i in range(auth.GLOBAL_MAX):
            self.login("wrong", environ_base={"REMOTE_ADDR": f"10.0.{i // 250}.{i % 250}"})
        r = self.login(environ_base={"REMOTE_ADDR": "10.9.9.9"})
        self.assertEqual(r.status_code, 429)

    def test_security_headers_and_cookie(self):
        r = self.login()
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        r = self.c.get("/")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_require_login_without_password_refuses(self):
        with self.assertRaises(RuntimeError):
            create_app(tempfile.mkdtemp(), tempfile.mkdtemp(), auth_options={"password_hash": "", "require_login": True})


class ServeTests(unittest.TestCase):
    def test_serve_behind_proxy_keeps_same_origin_and_client_address(self):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password(PW)
        os.environ["DASHBOARD_SECRET_KEY"] = "x"
        try:
            from dashboard import serve
            app = serve.build_app()
        finally:
            os.environ.pop("DASHBOARD_PASSWORD_HASH")
            os.environ.pop("DASHBOARD_SECRET_KEY")
        c = app.test_client()
        hdr = {"X-Forwarded-For": "100.64.0.7", "X-Forwarded-Host": "mac.tail1234.ts.net", "X-Forwarded-Proto": "https",
               "Origin": "https://mac.tail1234.ts.net"}
        r = c.post("/login", data={"password": "wrong"}, headers=hdr, base_url="http://127.0.0.1:8050")
        self.assertIn("Wrong password", r.get_data(as_text=True))       # same-origin passed through the proxy
        limiter = app.extensions["login_limiter"]
        self.assertIn("100.64.0.7", limiter.failures)                   # lockout keyed on the real client
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])


if __name__ == "__main__":
    unittest.main()
