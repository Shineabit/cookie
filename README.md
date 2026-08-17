# Cookie Auto-Login ULTIMATE Pro — version_one

A hardened rewrite of the cookie auto-login tool. Goal: **higher real login
success rate** by fixing the cookie-injection and verification bugs that made
the old 4.x versions fail or report false positives.

## What was broken (v4.x) and what we fixed

| # | Problem in v4.x | Fix in version_one |
|---|-----------------|--------------------|
| 1 | `__Host-` / `__Secure-` cookies were skipped entirely | Injected correctly: no `domain`, `path=/`, `Secure` |
| 2 | Dot-domains stripped (`lstrip('.')`), breaking subdomain cookies | Original domain preserved for normal cookies |
| 3 | `sameSite` / `httpOnly` / `expiry` never set on add_cookie | All propagated; secure cookies default `sameSite=None` |
| 4 | Dedupe keyed by name only | Keyed by `(name, domain)` |
| 5 | `_is_logged_in` returned success on "no indicator found" | Multi-signal: needs ≥2 positives and zero fail-indicators |
| 6 | `:contains()` CSS used (unsupported by Selenium) | Real text search + supported selectors |
| 7 | Fixed `time.sleep` waits | `WebDriverWait` + settle time for SSO redirects |
| 8 | HTTP pre-check marked success on a single weak keyword | Only short-circuits on high-confidence signal; else falls through to browser |
| 9 | `report_generator` module missing → app crashed on import | Added `report_generator.py` |
| 10 | 5 workers × full Chrome → memory crash = false failures | `max_workers` default 2, capped to cpu+1, profiles cleaned after run |
| 11 | Harmful `--disable-web-security` / site-isolation flags | Removed; uc handles stealth |
| 12 | `1.py` was a duplicate of `gui.py` | Dropped the duplicate |
| 13 | Cookie refresh always wrote JSON | Writes back in original format (Netscape preserved) |

## Files
- `main.py` — `CookieManager` (parsing, injection, verification, pre-check, concurrency)
- `gui.py` — Tkinter UI
- `report_generator.py` — standalone HTML report
- `site_rules.json` — per-domain login/fail indicators (edit to add sites)
- `requirements.txt`

## Install
```
cd /root/cookie/version_one
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
sudo apt install python3-tk      # if tkinter missing
```
A Chrome/Chromium binary is required (undetected-chromedriver downloads a matching driver).

## Run
```
python gui.py
```
1. Load a folder of `.txt` cookie files (JSON / Netscape / `name=value`).
2. (Optional) Mass Verify to check which cookies still grant sessions.
3. Login Selected / Login ALL Working.
4. Export CSV or HTML report.

## Tuning login success
- Edit `site_rules.json` to add per-site `login_selectors`, `logged_in_text`,
  `check_indicator`, and `fail_indicators`. Good rules = fewer false results.
- Keep "Pre-Check" on (cheap HTTP pass before launching a browser).
- If sites use TLS fingerprinting beyond uc's stealth, add a proxy / header
  profile — out of scope for this version.
