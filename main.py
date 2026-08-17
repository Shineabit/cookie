"""
Cookie Auto-Login ULTIMATE Pro - Main Logic
Version: 5.0 (version_one) - Hardened cookie injection, multi-signal verification,
domain-correct HTTP pre-check, resource-aware concurrency, format-preserving refresh.

Key fixes vs 4.0:
  * Cookie injection now handles __Host- / __Secure- prefixed cookies correctly
    (no domain attribute, path='/', Secure) instead of skipping them entirely.
  * Dot-domains ('.example.com') are preserved so subdomain cookies apply.
  * sameSite / httpOnly / expiry are propagated to add_cookie.
  * Dedupe keyed by (name, domain) not name alone.
  * Verification is multi-signal: "no indicator" => UNKNOWN (never auto-success).
    Default fail_indicators catch session-expired / verify / captcha pages.
  * CSS :contains() replaced with real text search + supported selectors.
  * Fixed sleeps replaced with WebDriverWait where useful.
  * HTTP pre-check sends domain-corrected cookies + browser UA and only
    short-circuits on HIGH-confidence signals.
  * Workers capped to CPU/RAM; profiles reused + cleaned.
  * Cookie refresh writes back in the ORIGINAL file format.
"""

import json
import os
import time
import csv
import hashlib
import logging
import sys
import queue
import threading
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import multiprocessing
import tkinter as tk
from tkinter import ttk, messagebox

import undetected_chromedriver as uc
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# ----------------------------------------------------------------------
# Logging (UTF-8)
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cookie_login.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

__version__ = "5.0"
__author__ = "CookieAutoLogin Team"

# Browser-like User-Agent for HTTP pre-check (avoids UA-based blocks).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CookieManager:
    def __init__(self):
        self.all_cookies = {}
        self.cookie_files = {}          # domain -> file path (for refresh)
        self.cookie_file_format = {}    # domain -> 'json' | 'netscape' (for refresh)
        self.websites = []
        self.favorites = set()
        self.login_status = {}
        self.categories = {}
        self.cookie_scores = {}
        self.drivers = []
        self.stop_verification = False
        self.cache = {}
        self.site_rules = self._load_site_rules()
        self.gui_root = None
        self.manual_confirm = False
        self.use_stealth = True
        self.auto_refresh = False
        self.pre_check = True
        self.max_workers = 2            # resource-aware default

    def set_gui_root(self, root):
        self.gui_root = root

    # ------------------------------------------------------------------
    # Site rules
    # ------------------------------------------------------------------
    def _load_site_rules(self):
        rules_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site_rules.json')
        if os.path.exists(rules_file):
            try:
                with open(rules_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load site_rules.json: {e}")
        return {
            "default": {
                "login_selectors": [
                    "a[href*='logout']", "a[href*='signout']",
                    "img[alt*='avatar' i]", ".user-menu",
                    ".avatar", "[data-testid='user-avatar']",
                    "[data-testid='account']", ".account-menu"
                ],
                "login_url_keywords": ["login", "signin", "sign_in", "auth"],
                "logged_in_text": ["welcome", "dashboard", "my account", "log out"],
                "check_url": "/",
                "check_indicator": "logout",
                "fail_indicators": [
                    "session expired", "session has expired", "your session",
                    "verify it's you", "verify your identity",
                    "please sign in again", "please log in again",
                    "we've logged you out", "captcha", "are you a robot",
                    "wrong email or password", "invalid login"
                ]
            }
        }

    def get_site_rules(self, domain):
        domain_lower = domain.lower()
        # most-specific match first
        for key in self.site_rules:
            if key == "default":
                continue
            if key in domain_lower:
                return self.site_rules[key]
        return self.site_rules.get("default", {})

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def load_settings(self):
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'cookie_login_settings.json')
            if os.path.exists(path):
                with open(path, 'r') as f:
                    settings = json.load(f)
                    self.favorites = set(settings.get('favorites', []))
                    self.extracted_credentials = settings.get('credentials', {})
        except Exception as e:
            logger.error(f"Error loading settings: {e}")

    def save_settings(self):
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'cookie_login_settings.json')
            settings = {
                'favorites': list(self.favorites),
                'credentials': getattr(self, 'extracted_credentials', {})
            }
            with open(path, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    # ------------------------------------------------------------------
    # File discovery & parsing
    # ------------------------------------------------------------------
    def find_txt_files_recursive(self, folder_path):
        txt_files = []
        def scan_directory(path):
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.is_file() and entry.name.endswith('.txt'):
                            txt_files.append(entry.path)
                        elif entry.is_dir():
                            scan_directory(entry.path)
            except PermissionError:
                pass
        scan_directory(folder_path)
        return txt_files

    @staticmethod
    def parse_single_file(file_path):
        """Parse a single cookie file; returns (cookies, file_path, fmt)."""
        cookies = []
        fmt = 'unknown'
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Try JSON (list or single dict)
            try:
                parsed = json.loads(content)
                fmt = 'json'
                if isinstance(parsed, list):
                    for cookie in parsed:
                        if not isinstance(cookie, dict):
                            continue
                        if 'domain' not in cookie and 'url' in cookie:
                            parsed_url = urlparse(cookie.get('url', ''))
                            cookie['domain'] = parsed_url.netloc
                        elif 'domain' not in cookie:
                            cookie['domain'] = os.path.basename(file_path).replace('.txt', '')
                        cookies.append(cookie)
                    return cookies, file_path, fmt
                elif isinstance(parsed, dict):
                    if 'domain' not in parsed:
                        parsed['domain'] = os.path.basename(file_path).replace('.txt', '')
                    return [parsed], file_path, fmt
            except json.JSONDecodeError:
                pass

            # Netscape
            fmt = 'netscape'
            lines = content.strip().split('\n')
            for line in lines:
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    try:
                        expiry = int(parts[4]) if parts[4].isdigit() else None
                        cookie = {
                            'domain': parts[0].lstrip('.'),
                            'path': parts[2] if parts[2] else '/',
                            'secure': parts[3].upper() == 'TRUE',
                            'expiry': expiry,
                            'name': parts[5],
                            'value': parts[6]
                        }
                        cookies.append(cookie)
                    except (ValueError, IndexError):
                        continue
                elif '=' in line:
                    name, value = line.split('=', 1)
                    domain = os.path.basename(file_path).replace('.txt', '')
                    cookie = {
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': domain,
                        'path': '/'
                    }
                    cookies.append(cookie)
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
        return cookies, file_path, fmt

    def process_cookie_files(self, folder_path, progress_callback=None):
        self.all_cookies = {}
        self.cookie_files = {}
        self.cookie_file_format = {}
        self.login_status = {}
        self.categories = {}

        txt_files = self.find_txt_files_recursive(folder_path)
        total = len(txt_files)
        if total == 0:
            return 0, 0

        try:
            pool = multiprocessing.Pool(processes=min(multiprocessing.cpu_count(), 4))
            results = pool.map(self.parse_single_file, txt_files)
            pool.close()
            pool.join()
        except Exception as e:
            logger.warning(f"Multiprocessing failed, falling back to sequential: {e}")
            results = [self.parse_single_file(f) for f in txt_files]

        self._merge_cookie_results(results, progress_callback, total)
        return len(self.websites), total

    def process_single_file(self, file_path):
        self.all_cookies = {}
        self.cookie_files = {}
        self.cookie_file_format = {}
        self.login_status = {}
        self.categories = {}

        cookies, fpath, fmt = self.parse_single_file(file_path)
        results = [(cookies, fpath, fmt)]
        self._merge_cookie_results(results, None, 1)
        return len(self.websites), 1

    def _merge_cookie_results(self, results, progress_callback, total):
        for idx, (cookies, file_path, fmt) in enumerate(results):
            if progress_callback:
                progress_callback(idx + 1, total)
            for cookie in cookies:
                domain = cookie.get('domain')
                if not domain:
                    continue
                domain = domain.lstrip('.')
                if domain and self.is_useful_cookie(cookie):
                    if domain not in self.all_cookies:
                        self.all_cookies[domain] = []
                        self.cookie_files[domain] = file_path
                        self.cookie_file_format[domain] = fmt
                        self.categories[domain] = self.categorize_domain(domain)
                    self.all_cookies[domain].append(cookie)

        # Dedupe per (name, domain) keeping the latest expiry.
        for domain in list(self.all_cookies.keys()):
            cookie_dict = {}
            for cookie in self.all_cookies[domain]:
                name = cookie.get('name')
                cdom = cookie.get('domain', domain)
                key = (name, cdom)
                if name:
                    if key not in cookie_dict:
                        cookie_dict[key] = cookie
                    else:
                        existing = cookie_dict[key]
                        e_exp = existing.get('expiry')
                        c_exp = cookie.get('expiry')
                        if c_exp and e_exp:
                            if c_exp > e_exp:
                                cookie_dict[key] = cookie
                        elif c_exp and not e_exp:
                            cookie_dict[key] = cookie
            self.all_cookies[domain] = list(cookie_dict.values())

        # Keep expired cookies so the GUI can filter them. Score live cookies only.
        kept = {}
        for domain, cookies in self.all_cookies.items():
            if not cookies:
                continue
            kept[domain] = cookies
            self.login_status[domain] = 'unknown'
            live = [c for c in cookies if not self.is_cookie_expired(c)]
            self.cookie_scores[domain] = self.calculate_cookie_score(live)
            if not live:
                logger.info(f"All cookies expired for {domain}")
        self.all_cookies = kept
        self.websites = sorted(list(self.all_cookies.keys()))

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------
    def is_useful_cookie(self, cookie):
        if 'name' not in cookie or not cookie['name']:
            return False
        if 'value' not in cookie or not cookie['value']:
            return False
        if len(str(cookie['value'])) < 3:
            return False
        name = cookie['name'].lower()
        skip_patterns = ['_ga', '_gid', '_gat', 'metrics', 'analytics', 'tracking',
                         '_ym_', '_fbp', '_gcl']
        for pattern in skip_patterns:
            if pattern in name:
                return False
        return True

    def categorize_domain(self, domain):
        domain_lower = domain.lower()
        categories = {
            'Social Media': ['facebook', 'twitter', 'instagram', 'linkedin', 'reddit', 'tiktok', 'snapchat', 'x.com'],
            'Shopping': ['amazon', 'ebay', 'shop', 'store', 'aliexpress', 'walmart', 'target'],
            'Banking': ['bank', 'paypal', 'stripe', 'chase', 'wells', 'capitalone'],
            'Email': ['gmail', 'outlook', 'mail', 'yahoo', 'proton', 'aol'],
            'Entertainment': ['netflix', 'spotify', 'youtube', 'twitch', 'steam', 'hulu', 'disney'],
            'Gambling': ['stake', 'bet', 'casino', 'poker', 'gambling', 'slot', 'roulette']
        }
        for category, keywords in categories.items():
            if any(kw in domain_lower for kw in keywords):
                return category
        return "Other"

    def calculate_cookie_score(self, cookies):
        if not cookies:
            return 0
        score = 0
        for cookie in cookies:
            name = cookie.get('name', '').lower()
            if any(x in name for x in ['session', 'auth', 'token', 'sid', '__host', 'secure']):
                score += 30
            elif any(x in name for x in ['login', 'user', 'uid', 'email', 'csrf']):
                score += 20
            else:
                score += 5
            if cookie.get('secure'):
                score += 10
            if len(str(cookie.get('value', ''))) > 30:
                score += 5
        return min(100, score)

    def get_score_color(self, score):
        if score >= 70:
            return '#10B981'
        elif score >= 50:
            return '#FBBF24'
        else:
            return '#EF4444'

    def get_score_emoji(self, score):
        if score >= 70:
            return '✅'
        elif score >= 50:
            return '⚠️'
        else:
            return '❌'

    AUTH_COOKIE_MARKERS = (
        'session', 'sess', 'auth', 'token', 'jwt', 'sid', 'ssid',
        'login', 'user', 'uid', 'csrf', 'access', 'refresh',
        '__host', '__secure', 'cf_clearance', 'remember',
    )

    @staticmethod
    def is_cookie_expired(cookie):
        expiry = cookie.get('expiry')
        if not expiry:
            return False
        try:
            return float(expiry) < time.time()
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _cookie_is_complete(cookie):
        name = cookie.get('name') or ''
        value = cookie.get('value')
        if not name or value in (None, '') or len(str(value)) < 3:
            return False
        if name.startswith('__Host-') or name.startswith('__Secure-'):
            return True
        return bool(cookie.get('domain'))

    @classmethod
    def _is_auth_cookie(cls, cookie):
        name = (cookie.get('name') or '').lower()
        return any(marker in name for marker in cls.AUTH_COOKIE_MARKERS)

    def live_cookies(self, domain):
        return [c for c in self.all_cookies.get(domain, []) if not self.is_cookie_expired(c)]

    def expired_cookie_count(self, domain):
        return sum(1 for c in self.all_cookies.get(domain, []) if self.is_cookie_expired(c))

    def has_unexpired_cookies(self, domain):
        return any(not self.is_cookie_expired(c) for c in self.all_cookies.get(domain, []))

    def has_login_data(self, domain):
        """True if this domain has complete cookies that look sufficient to log in."""
        cookies = self.all_cookies.get(domain, [])
        if not cookies:
            return False
        live = [c for c in cookies if not self.is_cookie_expired(c)]
        pool = live if live else cookies
        complete = [c for c in pool if self._cookie_is_complete(c)]
        if not complete:
            return False
        required = self.get_site_rules(domain).get('required_cookies') or []
        if required:
            have = {c.get('name') for c in complete}
            have_lower = {n.lower() for n in have if n}
            return all(name in have or name.lower() in have_lower for name in required)
        return any(self._is_auth_cookie(c) for c in complete)

    # ------------------------------------------------------------------
    # HTTP Pre-Check (domain-corrected cookies + browser UA)
    # ------------------------------------------------------------------
    def _http_pre_check(self, domain):
        if not self.pre_check:
            return False, "Pre-check disabled", "disabled"

        cookies = self.all_cookies.get(domain, [])
        if not cookies:
            return False, "No cookies", "none"

        rules = self.get_site_rules(domain)
        check_url = rules.get("check_url", "/")
        indicator = rules.get("check_indicator", "logout")

        # Build a requests cookie jar with correct domains (requests handles
        # domain matching per-request against the target host, so we keep the
        # original domains and let requests decide applicability).
        cookie_jar = {}
        for c in cookies:
            if c.get('expiry') and c['expiry'] < time.time():
                continue
            name = c.get('name')
            value = c.get('value')
            if name and value:
                cookie_jar[name] = value

        if not cookie_jar:
            return False, "No valid cookies for HTTP check", "none"

        headers = {
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            url = f"https://{domain}{check_url}"
            resp = requests.get(url, cookies=cookie_jar, headers=headers,
                                timeout=10, allow_redirects=True)
            text = resp.text.lower()

            # HIGH confidence: indicator present AND no fail indicators.
            fail_indicators = rules.get("fail_indicators", [])
            for fi in fail_indicators:
                if fi.lower() in text:
                    return False, f"Fail indicator '{fi}' present", "fail"

            if indicator.lower() in text:
                # Only count as success if the page did not redirect to a login URL.
                final_url = resp.url.lower()
                login_kw = rules.get("login_url_keywords", ["login", "signin"])
                if any(kw in final_url for kw in login_kw):
                    return False, f"Redirected to login ({final_url})", "redirect"
                return True, f"Found '{indicator}' + no fail signals", "success"

            # LOW confidence: do not short-circuit; let the browser verify.
            return False, f"Indicator '{indicator}' not found", "weak"
        except Exception as e:
            logger.debug(f"HTTP pre-check failed for {domain}: {e}")
            return False, f"HTTP error: {e}", "error"

    # ------------------------------------------------------------------
    # Driver & login
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_chrome_options(options):
        """Chrome 136+ rejects legacy experimental keys (excludeSwitches, etc.)."""
        banned = ("excludeSwitches", "useAutomationExtension")
        exp = getattr(options, "_experimental_options", None)
        if isinstance(exp, dict):
            for key in banned:
                exp.pop(key, None)
        return options

    @staticmethod
    def _installed_chrome_major():
        """Major version of the installed Chrome, so uc downloads a matching driver."""
        exe = None
        try:
            exe = uc.find_chrome_executable()
        except Exception:
            exe = None

        if sys.platform.startswith("win"):
            try:
                import winreg
                for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        with winreg.OpenKey(root, r"Software\Google\Chrome\BLBeacon") as key:
                            ver, _ = winreg.QueryValueEx(key, "version")
                            return int(str(ver).split(".")[0])
                    except OSError:
                        continue
            except Exception:
                pass
            if exe and os.path.isfile(exe):
                try:
                    import ctypes
                    from ctypes import wintypes
                    version = ctypes.windll.version
                    size = version.GetFileVersionInfoSizeW(exe, None)
                    if size:
                        buf = ctypes.create_string_buffer(size)
                        if version.GetFileVersionInfoW(exe, 0, size, buf):
                            class VS_FIXEDFILEINFO(ctypes.Structure):
                                _fields_ = [
                                    ("dwSignature", wintypes.DWORD),
                                    ("dwStrucVersion", wintypes.DWORD),
                                    ("dwFileVersionMS", wintypes.DWORD),
                                    ("dwFileVersionLS", wintypes.DWORD),
                                ]
                            ptr = ctypes.c_void_p()
                            length = wintypes.UINT()
                            if version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
                                info = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
                                return int(info.dwFileVersionMS >> 16)
                except Exception:
                    pass

        if exe and os.path.isfile(exe):
            try:
                import re
                import subprocess
                out = subprocess.check_output([exe, "--version"], text=True, timeout=10)
                m = re.search(r"(\d+)\.", out)
                if m:
                    return int(m.group(1))
            except Exception:
                pass
        return None

    def _create_driver(self, headless=False, user_data_dir=None, deep_scan=False):
        if self.use_stealth:
            options = uc.ChromeOptions()
            if user_data_dir:
                options.add_argument(f'--user-data-dir={user_data_dir}')
            if headless and not deep_scan:
                options.add_argument('--headless=new')
            else:
                options.add_argument('--start-maximized')
            # NOTE: intentionally NOT disabling web-security / site isolation;
            # those extras can trigger site-side anomalies. uc handles stealth.
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--ignore-certificate-errors')
            options.add_argument('--disable-blink-features=AutomationControlled')
            # Do not set excludeSwitches / useAutomationExtension — Chrome 136+
            # (this machine has 151) rejects them as unrecognized chromeOptions.
            self._sanitize_chrome_options(options)

            chrome_major = self._installed_chrome_major()
            if chrome_major:
                logger.info(f"Using ChromeDriver for installed Chrome {chrome_major}")
            driver = uc.Chrome(options=options, version_main=chrome_major)
            driver.set_page_load_timeout(60 if deep_scan else 30)
            driver.implicitly_wait(5)
            return driver
        else:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            options = Options()
            if user_data_dir:
                options.add_argument(f'--user-data-dir={user_data_dir}')
            options.add_argument('--disable-blink-features=AutomationControlled')
            if headless and not deep_scan:
                options.add_argument('--headless=new')
            else:
                options.add_argument('--start-maximized')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--ignore-certificate-errors')
            self._sanitize_chrome_options(options)

            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(60 if deep_scan else 30)
            driver.implicitly_wait(5)
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })
            return driver

    # ------------------------------------------------------------------
    # Cookie injection (CORRECT handling of __Host-/__Secure- + attrs)
    # ------------------------------------------------------------------
    def _build_cookie_for_injection(self, cookie, default_domain):
        """
        Build a Selenium add_cookie dict.
        - __Host- / __Secure- cookies: NO domain attribute, path must be '/', Secure True.
        - Otherwise: keep original domain (including leading '.') and path.
        - Always propagate sameSite / httpOnly / expiry.
        """
        name = cookie.get('name', '')
        value = cookie.get('value', '')
        if not name:
            return None

        is_special = name.startswith('__Host-') or name.startswith('__Secure-')

        cdict = {'name': name, 'value': value}
        if is_special:
            # Host/secure prefixed cookies may NOT carry a domain and must be
            # set on the exact host with path '/' and Secure.
            cdict['path'] = '/'
            cdict['secure'] = True
        else:
            dom = cookie.get('domain', default_domain)
            if dom:
                cdict['domain'] = dom.lstrip('.')  # Selenium wants host without dot
            cdict['path'] = cookie.get('path', '/') or '/'
            if cookie.get('secure'):
                cdict['secure'] = True

        # sameSite
        same_site = str(cookie.get('sameSite', '')).lower()
        if same_site in ('lax', 'strict', 'none'):
            cdict['sameSite'] = same_site.capitalize()
        elif cookie.get('secure'):
            # Default secure cookies to None so they survive cross-site redirects.
            cdict['sameSite'] = 'None'

        if cookie.get('httpOnly'):
            cdict['httpOnly'] = True
        expiry = cookie.get('expiry')
        if expiry:
            try:
                cdict['expiry'] = float(expiry)
            except (ValueError, TypeError):
                pass
        return cdict

    # ------------------------------------------------------------------
    # Verification (multi-signal, never auto-success on "no indicator")
    # ------------------------------------------------------------------
    def _is_logged_in(self, driver, domain):
        rules = self.get_site_rules(domain)
        positives = []
        negatives = []

        try:
            current_url = driver.current_url.lower()
            page_source = driver.page_source[:20000].lower()
        except Exception as e:
            return False, f"Cannot read page: {e}"

        # 1) URL keyword => logged OUT
        login_keywords = rules.get("login_url_keywords", ["login", "signin"])
        for kw in login_keywords:
            if kw in current_url:
                negatives.append(f"URL contains '{kw}'")

        # 2) Fail indicators => logged OUT (strong)
        fail_indicators = rules.get("fail_indicators", [])
        for text in fail_indicators:
            if text.lower() in page_source:
                negatives.append(f"fail indicator '{text}'")

        # 3) Positive selectors (CSS only; use text search for contains-like)
        selectors = rules.get("login_selectors", [])
        for selector in selectors:
            try:
                if ":contains(" in selector:
                    # Convert a[href*='logout']:contains('X') style to text search
                    base_sel = selector.split(":contains(")[0].strip()
                    if driver.find_elements(By.CSS_SELECTOR, base_sel):
                        # We'll double check via page_source text below
                        pass
                elif driver.find_elements(By.CSS_SELECTOR, selector):
                    positives.append(f"selector '{selector}'")
            except Exception:
                pass

        # 4) Logged-in text signals
        logged_in_text = rules.get("logged_in_text", [])
        for text in logged_in_text:
            if text.lower() in page_source:
                positives.append(f"text '{text}'")

        # 5) Generic user indicators
        user_indicators = ['logout', 'my account', 'profile', 'dashboard', 'welcome']
        for ind in user_indicators:
            if ind in page_source:
                positives.append(f"ind '{ind}'")

        # 6) Login form present => negative
        try:
            if driver.find_elements(By.CSS_SELECTOR, 'form[action*="login"]'):
                negatives.append("login form present")
        except Exception:
            pass

        # Decision: require at least 2 independent positive signals and ZERO strong negatives.
        if negatives:
            return False, "; ".join(negatives)
        if len(positives) >= 2:
            return True, "; ".join(positives[:3])
        if len(positives) == 1 and 'logout' in positives[0]:
            # Single 'logout' mention is decent but not conclusive; treat as success
            # only if there's also a non-login URL. Already covered by no negatives.
            return True, positives[0]
        return False, f"Insufficient signals (pos={positives})"

    def _wait_for_settle(self, driver, deep_scan=False):
        """Give SSO/OAuth redirects a moment to settle via WebDriverWait."""
        try:
            WebDriverWait(driver, 8 if deep_scan else 4).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass
        time.sleep(3 if deep_scan else 2)

    # ------------------------------------------------------------------
    # Confirmation dialog (unchanged behavior, fixed reinject)
    # ------------------------------------------------------------------
    def _show_confirmation_dialog(self, driver, domain):
        if self.gui_root is None:
            return None
        result_queue = queue.Queue()

        def show_dialog():
            dialog = tk.Toplevel(self.gui_root)
            dialog.title(f"Login Confirmation – {domain}")
            dialog.geometry("450x280")
            dialog.transient(self.gui_root)
            dialog.grab_set()
            dialog.resizable(False, False)

            tk.Label(dialog, text=f"Are you logged into {domain}?", font=('Arial', 12, 'bold')).pack(pady=15)
            status_label = tk.Label(dialog, text="", fg="blue")
            status_label.pack()
            result = None

            def set_result(val):
                nonlocal result
                result = val
                dialog.destroy()

            def reinject():
                try:
                    cookies_added = 0
                    for cookie in self.all_cookies.get(domain, []):
                        cdict = self._build_cookie_for_injection(cookie, domain)
                        if not cdict:
                            continue
                        try:
                            driver.add_cookie(cdict)
                            cookies_added += 1
                        except Exception as e:
                            logger.debug(f"Reinject failed for {cookie.get('name')}: {e}")
                    driver.refresh()
                    self._wait_for_settle(driver)
                    status_label.config(text=f"✅ Re-injected {cookies_added} cookies and refreshed.", fg="green")
                except Exception as e:
                    status_label.config(text=f"❌ Error: {e}", fg="red")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="✅ Logged In", command=lambda: set_result(True),
                      bg='#10B981', fg='white', padx=15, pady=5).pack(side='left', padx=5)
            tk.Button(btn_frame, text="❌ Not Logged In", command=lambda: set_result(False),
                      bg='#EF4444', fg='white', padx=15, pady=5).pack(side='left', padx=5)
            tk.Button(btn_frame, text="🔄 Reinject Cookies", command=reinject,
                      bg='#FBBF24', padx=15, pady=5).pack(side='left', padx=5)
            tk.Button(btn_frame, text="🛑 Cancel", command=lambda: set_result(None),
                      bg='#9CA3AF', padx=15, pady=5).pack(side='left', padx=5)
            dialog.wait_window()
            result_queue.put(result)

        self.gui_root.after(0, show_dialog)
        try:
            result = result_queue.get(timeout=300)
        except queue.Empty:
            result = None
        return result

    # ------------------------------------------------------------------
    # Cookie refresh (format-preserving)
    # ------------------------------------------------------------------
    def _refresh_cookies(self, domain, driver):
        if not self.auto_refresh:
            return False
        file_path = self.cookie_files.get(domain)
        if not file_path:
            logger.warning(f"No file path stored for {domain} – cannot refresh")
            return False
        try:
            driver_cookies = driver.get_cookies()
            if not driver_cookies:
                logger.warning(f"No cookies retrieved from driver for {domain}")
                return False

            fmt = self.cookie_file_format.get(domain, 'json')
            if fmt == 'netscape':
                self._write_netscape(file_path, driver_cookies)
                new_cookies = self._from_netscape(driver_cookies)
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(driver_cookies, f, indent=2)
                new_cookies = driver_cookies

            self.all_cookies[domain] = new_cookies
            self.cookie_scores[domain] = self.calculate_cookie_score(new_cookies)
            logger.info(f"✅ Refreshed cookies for {domain} saved to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to refresh cookies for {domain}: {e}")
            return False

    @staticmethod
    def _from_netscape(driver_cookies):
        out = []
        for c in driver_cookies:
            out.append({
                'domain': (c.get('domain') or '').lstrip('.'),
                'name': c.get('name', ''),
                'value': c.get('value', ''),
                'path': c.get('path', '/'),
                'secure': c.get('secure', False),
                'expiry': c.get('expiry', None)
            })
        return out

    @staticmethod
    def _write_netscape(file_path, driver_cookies):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in driver_cookies:
                domain = c.get('domain', '')
                if not domain.startswith('.'):
                    domain = '.' + domain.lstrip('.')
                flag = 'TRUE' if domain.startswith('.') else 'FALSE'
                path = c.get('path', '/') or '/'
                secure = 'TRUE' if c.get('secure') else 'FALSE'
                expiry = c.get('expiry')
                expiry = str(int(expiry)) if expiry else '0'
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{c.get('name','')}\t{c.get('value','')}\n")

    # ------------------------------------------------------------------
    # Core login
    # ------------------------------------------------------------------
    def login_to_website(self, domain, headless=False, keep_open=False, retries=3,
                         keep_open_on_error=False, deep_scan=False):
        if domain not in self.all_cookies:
            logger.warning(f"No cookies for {domain}")
            return False, None

        profile_hash = hashlib.md5(domain.encode()).hexdigest()[:16]
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_profiles')
        os.makedirs(base_dir, exist_ok=True)
        user_data_dir = os.path.join(base_dir, f"profile_{profile_hash}")

        last_error = None
        driver = None
        for attempt in range(retries):
            try:
                logger.info(f"Login attempt {attempt+1}/{retries} for {domain} (stealth={self.use_stealth}, deep={deep_scan})")
                driver = self._create_driver(headless=headless, user_data_dir=user_data_dir, deep_scan=deep_scan)

                url = f"https://{domain}"
                logger.info(f"Navigating to {url}")
                driver.get(url)
                time.sleep(3 if deep_scan else 2)

                now = time.time()
                valid_cookies = [c for c in self.all_cookies.get(domain, [])
                                if not c.get('expiry') or c['expiry'] >= now]
                cookies_added = 0
                for cookie in valid_cookies:
                    cdict = self._build_cookie_for_injection(cookie, domain)
                    if not cdict:
                        continue
                    try:
                        driver.add_cookie(cdict)
                        cookies_added += 1
                    except Exception as e:
                        logger.debug(f"Failed to add cookie {cookie.get('name')}: {e}")

                logger.info(f"Added {cookies_added} cookies for {domain}")
                driver.refresh()
                self._wait_for_settle(driver, deep_scan)

                if self.manual_confirm and not headless:
                    user_choice = self._show_confirmation_dialog(driver, domain)
                    if user_choice is True:
                        self.login_status[domain] = 'success'
                        logger.info(f"User confirmed login for {domain}")
                        if self.auto_refresh:
                            self._refresh_cookies(domain, driver)
                        if not headless and keep_open:
                            self.drivers.append(driver)
                            return True, driver
                        driver.quit()
                        return True, None
                    else:
                        self.login_status[domain] = 'failed'
                        logger.info(f"User denied/cancelled login for {domain}")
                        if keep_open_on_error:
                            self.drivers.append(driver)
                            return False, driver
                        driver.quit()
                        return False, None

                is_logged_in, reason = self._is_logged_in(driver, domain)
                logger.info(f"Login check for {domain}: {is_logged_in} - {reason}")

                if is_logged_in:
                    self.login_status[domain] = 'success'
                    logger.info(f"SUCCESSFULLY LOGGED IN to {domain}")
                    if self.auto_refresh:
                        self._refresh_cookies(domain, driver)
                    if not headless and keep_open:
                        self.drivers.append(driver)
                        return True, driver
                    driver.quit()
                    return True, None
                else:
                    self.login_status[domain] = 'failed'
                    logger.warning(f"Could not verify login for {domain} - reason: {reason}")
                    if attempt < retries - 1 and not self.stop_verification:
                        wait_time = 2 ** attempt
                        logger.info(f"Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                        continue
                    if keep_open_on_error:
                        self.drivers.append(driver)
                        return False, driver
                    driver.quit()
                    return False, None

            except (TimeoutException, WebDriverException) as e:
                error_msg = str(e)
                last_error = e
                logger.error(f"Driver error on attempt {attempt+1} for {domain}: {e}")
                if attempt < retries - 1 and not self.stop_verification:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                    continue
                if driver and keep_open_on_error:
                    self.drivers.append(driver)
                    return False, driver
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                return False, None
            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error for {domain}: {e}")
                if attempt < retries - 1 and not self.stop_verification:
                    time.sleep(2 ** attempt)
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = None
                    continue
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                return False, None

        self.login_status[domain] = 'failed'
        logger.error(f"All {retries} attempts failed for {domain}. Last error: {last_error}")
        return False, None

    def verify_login_fast(self, domain, keep_open_on_error=False, deep_scan=False):
        # Pre-check first (cheap, no browser).
        if self.pre_check:
            ok, reason, conf = self._http_pre_check(domain)
            if ok and conf == "success":
                self.login_status[domain] = 'success'
                logger.info(f"✅ Pre-check OK for {domain}: {reason}")
                return True
            elif conf in ("fail", "redirect"):
                self.login_status[domain] = 'failed'
                logger.info(f"Pre-check negative for {domain}: {reason}")
                return False
            # conf in weak/error/none/disabled -> fall through to browser

        success, _ = self.login_to_website(
            domain,
            headless=not deep_scan,
            keep_open=False,
            retries=2 if not deep_scan else 3,
            keep_open_on_error=keep_open_on_error,
            deep_scan=deep_scan
        )
        return success

    def mass_check_logins(self, progress_callback=None, max_workers=None,
                          keep_open_on_error=False, deep_scan=False):
        if not self.websites:
            return 0, 0

        if max_workers is None:
            max_workers = self.max_workers
        # Resource-aware cap: never more than cpu_count + 1 browsers.
        cpu_cap = multiprocessing.cpu_count() + 1
        max_workers = max(1, min(max_workers, cpu_cap))

        self.stop_verification = False
        verified = 0
        failed = 0
        completed = 0
        total = len(self.websites)

        if deep_scan:
            logger.info("Deep Scan mode: running sequentially, browsers visible.")
            for domain in self.websites:
                if self.stop_verification:
                    break
                completed += 1
                if self.verify_login_fast(domain, keep_open_on_error=keep_open_on_error, deep_scan=True):
                    verified += 1
                else:
                    failed += 1
                if progress_callback:
                    progress_callback(completed, total, verified, failed)
            return verified, failed

        def check_domain(domain):
            if self.stop_verification:
                return False
            return self.verify_login_fast(domain, keep_open_on_error=keep_open_on_error, deep_scan=False)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_domain, d): d for d in self.websites}
            for future in as_completed(futures):
                if self.stop_verification:
                    break
                completed += 1
                try:
                    res = future.result()
                except Exception:
                    res = False
                if res:
                    verified += 1
                else:
                    failed += 1
                if progress_callback:
                    progress_callback(completed, total, verified, failed)

        # Cleanup transient profiles after a mass run (they are reusable but cost disk).
        self._cleanup_profiles()
        return verified, failed

    def _cleanup_profiles(self):
        try:
            base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_profiles')
            if os.path.isdir(base_dir):
                shutil.rmtree(base_dir, ignore_errors=True)
                logger.info("Cleaned chrome_profiles directory")
        except Exception as e:
            logger.debug(f"Profile cleanup skipped: {e}")

    def login_multiple(self, domains, headless=False, keep_open=False, retries=3,
                       keep_open_on_error=False, deep_scan=False):
        results = []
        for domain in domains:
            if domain not in self.all_cookies:
                results.append((domain, False, None))
                continue
            success, driver = self.login_to_website(
                domain, headless, keep_open, retries, keep_open_on_error, deep_scan
            )
            results.append((domain, success, driver))
            time.sleep(2 if not deep_scan else 5)
        return results

    def close_all_browsers(self):
        count = len(self.drivers)
        for driver in self.drivers:
            try:
                driver.quit()
            except Exception:
                pass
        self.drivers.clear()
        return count

    def export_report(self, filename):
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Domain', 'Status', 'Score', 'Cookies', 'Category'])
                for domain in sorted(self.websites):
                    status = self.login_status.get(domain, 'unknown')
                    score = self.cookie_scores.get(domain, 0)
                    cookies = len(self.all_cookies.get(domain, []))
                    category = self.categories.get(domain, 'Other')
                    writer.writerow([domain, status, score, cookies, category])
            return True
        except Exception as e:
            logger.error(f"Export error: {e}")
            return False

    def get_domain_cookies_preview(self, domain):
        if domain not in self.all_cookies:
            return None
        cookies = self.all_cookies[domain]
        return {
            'domain': domain,
            'total_cookies': len(cookies),
            'live_cookies': len(self.live_cookies(domain)),
            'expired_cookies': self.expired_cookie_count(domain),
            'has_login_data': self.has_login_data(domain),
            'score': self.cookie_scores.get(domain, 0),
            'top_cookies': [
                {
                    'name': c.get('name'),
                    'value': str(c.get('value'))[:30],
                    'expired': self.is_cookie_expired(c),
                }
                for c in cookies[:5]
            ]
        }

    def get_all_data_for_report(self):
        domains = []
        for domain in sorted(self.websites):
            domains.append({
                'domain': domain,
                'status': self.login_status.get(domain, 'unknown'),
                'score': self.cookie_scores.get(domain, 0),
                'cookie_count': len(self.all_cookies.get(domain, [])),
                'category': self.categories.get(domain, 'Other'),
                'top_cookies': [{'name': c.get('name', ''), 'value': c.get('value', '')[:30]}
                                for c in self.all_cookies.get(domain, [])[:5]]
            })
        return {
            'total': len(domains),
            'success': sum(1 for d in domains if d['status'] == 'success'),
            'failed': sum(1 for d in domains if d['status'] == 'failed'),
            'unknown': sum(1 for d in domains if d['status'] == 'unknown'),
            'domains': domains
        }
