"""
Self-test for version_one logic. No real browser / GUI required.
Run:  python3 _selftest.py
"""
import json, os, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import CookieManager

passed = 0
failed = 0

def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")

print("== Parsing (JSON / Netscape / name=value) ==")
cm = CookieManager()

# JSON list
jf = "/tmp/_t_json.txt"
with open(jf, "w") as f:
    json.dump([
        {"domain": ".example.com", "name": "sess", "value": "abc123", "secure": True,
         "sameSite": "None", "httpOnly": True, "expiry": time.time() + 99999},
        {"domain": "example.com", "name": "__Host-sid", "value": "xyz", "secure": True, "path": "/"}
    ], f)
cookies, fp, fmt = cm.parse_single_file(jf)
check("json parsed 2 cookies", len(cookies) == 2)
check("json fmt detected", fmt == "json")

# Netscape
nf = "/tmp/_t_netscape.txt"
with open(nf, "w") as f:
    f.write("# Netscape\n")
    f.write(".sub.example.com\tTRUE\t/\tTRUE\t0\tauth\ttokenval\n")
cookies2, fp2, fmt2 = cm.parse_single_file(nf)
check("netscape parsed 1 cookie", len(cookies2) == 1)
check("netscape fmt detected", fmt2 == "netscape")
check("netscape keeps dot domain", cookies2[0]['domain'] == "sub.example.com")

# Expired cookie is kept (GUI filters it)
ef = "/tmp/_t_exp.txt"
with open(ef, "w") as f:
    json.dump([{"domain": "x.com", "name": "old", "value": "v", "expiry": 1}], f)
c3, _, _ = cm.parse_single_file(ef)
check("expired cookie kept", len(c3) == 1)
check("expired cookie flagged", CookieManager.is_cookie_expired(c3[0]) is True)

print("== Login-data / expiry filters ==")
cmf = CookieManager()
cmf.all_cookies = {
    "live.example": [
        {"domain": "live.example", "name": "sessionid", "value": "abc123xyz", "expiry": time.time() + 9999}
    ],
    "dead.example": [
        {"domain": "dead.example", "name": "sessionid", "value": "oldtoken12", "expiry": 1}
    ],
    "track.example": [
        {"domain": "track.example", "name": "pref", "value": "darkmodeok"}
    ],
}
check("live has unexpired", cmf.has_unexpired_cookies("live.example"))
check("dead has no unexpired", cmf.has_unexpired_cookies("dead.example") is False)
check("session cookie is login data", cmf.has_login_data("live.example"))
check("pref cookie is not login data", cmf.has_login_data("track.example") is False)
check("expired session still counts as login data", cmf.has_login_data("dead.example"))

print("== Cookie injection dict building ==")
# normal cookie keeps domain, secure, sameSite, httpOnly, expiry
normal = {"domain": ".example.com", "name": "sess", "value": "abc", "secure": True,
          "same" if False else "sameSite": "None", "httpOnly": True, "expiry": time.time() + 100}
# note: above dict literal trick is ugly; build explicitly instead:
normal = {"domain": ".example.com", "name": "sess", "value": "abc", "secure": True,
          "sameSite": "None", "httpOnly": True, "expiry": time.time() + 100}
d = cm._build_cookie_for_injection(normal, "example.com")
check("normal: domain host-only (no dot)", d.get('domain') == "example.com")
check("normal: secure set", d.get('secure') is True)
check("normal: sameSite None", d.get('sameSite') == "None")
check("normal: httpOnly set", d.get('httpOnly') is True)
check("normal: expiry set", 'expiry' in d)

# __Host- cookie: NO domain, path '/', secure True
special = {"domain": "example.com", "name": "__Host-sid", "value": "xyz", "secure": True, "path": "/"}
ds = cm._build_cookie_for_injection(special, "example.com")
check("__Host: no domain attr", 'domain' not in ds)
check("__Host: path /", ds.get('path') == "/")
check("__Host: secure True", ds.get('secure') is True)

# __Secure- cookie with no secure flag -> forced secure
sec = {"domain": "example.com", "name": "__Secure-id", "value": "v", "path": "/"}
ds2 = cm._build_cookie_for_injection(sec, "example.com")
check("__Secure: no domain attr", 'domain' not in ds2)
check("__Secure: forced secure", ds2.get('secure') is True)

print("== Dedupe by (name, domain) ==")
cm.all_cookies = {}
cm.cookie_files = {}
cm.cookie_file_format = {}
res = [
    ([
        {"domain": "a.com", "name": "x", "value": "val1"},
        {"domain": "a.com", "name": "x", "value": "val2"},  # dup by name+domain
    ], "/tmp/a.txt", "json"),
    ([
        {"domain": "b.com", "name": "x", "value": "val3"},   # same name diff domain -> separate
    ], "/tmp/b.txt", "json"),
]
cm._merge_cookie_results(res, None, 1)
check("a.com has 1 cookie (deduped)", len(cm.all_cookies.get("a.com", [])) == 1)
check("b.com has 1 cookie (separate)", len(cm.all_cookies.get("b.com", [])) == 1)

print("== Verification decision (multi-signal) ==")
# Build a fake driver with a page_source + current_url
class FakeDriver:
    def __init__(self, url, source):
        self._url = url; self._src = source
    @property
    def current_url(self): return self._url
    @property
    def page_source(self): return self._src

# Logged-out page: login url + 'please sign in again'
dm = CookieManager()
dm.site_rules = cm.site_rules
fd = FakeDriver("https://x.com/login", "please sign in again <form action='/login'>")
ok, reason = dm._is_logged_in(fd, "x.com")
check("logout page => not logged in", ok is False)

# Logged-in page: contains logout + dashboard + my account (>=2 positives, no negatives)
fd2 = FakeDriver("https://x.com/home", "welcome to your dashboard <a href='/logout'>log out</a> my account")
ok2, r2 = dm._is_logged_in(fd2, "x.com")
check("dashboard+logout+account => logged in", ok2 is True)

# Ambiguous page: only 'profile' text once, no negatives, but <1 pos => not success
fd3 = FakeDriver("https://x.com/p", "just a profile word here nothing else")
ok3, r3 = dm._is_logged_in(fd3, "x.com")
check("single weak signal => NOT auto-success", ok3 is False)

print("== HTTP pre-check (no real network; monkeypatch requests) ==")
import main as M
dm.all_cookies = {"x.com": [{"name": "sess", "value": "abcdef123456", "domain": "x.com"}]}
class FakeResp:
    def __init__(self, text, url="https://x.com/", status=200):
        self.text = text; self.url = url; self.status_code = status
# success case: indicator present, no fail, no login redirect
M.requests.get = lambda *a, **k: FakeResp("here is your <a>logout</a> dashboard")
okp, rp, cp = dm._http_pre_check("x.com")
check("precheck success signal", okp is True and cp == "success")

# fail indicator case
M.requests.get = lambda *a, **k: FakeResp("your session has expired please sign in again")
okf, rf, cf = dm._http_pre_check("x.com")
check("precheck fail signal", okf is False and cf == "fail")

# weak case: indicator absent
M.requests.get = lambda *a, **k: FakeResp("welcome guest, nothing here")
okw, rw, cw = dm._http_pre_check("x.com")
check("precheck weak (no short-circuit)", okw is False and cw == "weak")

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
