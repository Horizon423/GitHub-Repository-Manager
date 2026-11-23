#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Repository Manager & Bulk Folder Uploader
for Android Termux (Python 3.8+, standard library only, real Git).

Browse your public/private repositories, create or delete repositories and
bulk-upload folders from internal storage with a real git add / commit / push,
without ever touching the content that is already in the repository.

License: BSD 3-Clause (full text in README.md)
"""

import argparse
import base64
import filecmp
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

APP_NAME = "GitHub Repository Manager"
APP_TAGLINE = "Bulk Folder Uploader for Android Termux"
VERSION = "1.0.0"
USER_AGENT = "github-repo-manager-termux/" + VERSION

MAX_FILE_BYTES = 100 * 1024 * 1024    # GitHub rejects files of 100 MiB and above
WARN_FILE_BYTES = 50 * 1024 * 1024    # GitHub warns above 50 MiB
WARN_TOTAL_BYTES = 500 * 1024 * 1024  # very large pushes may time out on mobile data


# ============================================================================
# Styling: White & Green ANSI theme (auto-disabled when output is not a TTY)
# ============================================================================
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

USE_COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ
             and os.environ.get("TERM", "") != "dumb")
UTF8 = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") == "utf8"


def _ansi(code):
    return "\033[%sm" % code if USE_COLOR else ""


G = _ansi("92")      # bright green
DG = _ansi("32")     # dark green
W = _ansi("97")      # bright white
R = _ansi("91")      # red
Y = _ansi("93")      # yellow
DIM = _ansi("2")
B = _ansi("1")
X = _ansi("0")

if UTF8:
    S_FULL, S_EMPTY = "\u2588", "\u2591"
    SPIN = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c",
            "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"]
    H, V, TL, TR, BL, BR = "\u2500", "\u2502", "\u250c", "\u2510", "\u2514", "\u2518"
    S_PROMPT, S_DOT, S_ARROW = "\u276f", "\u25cf", "\u2192"
else:
    S_FULL, S_EMPTY = "#", "-"
    SPIN = ["|", "/", "-", "\\"]
    H, V, TL, TR, BL, BR = "-", "|", "+", "+", "+", "+"
    S_PROMPT, S_DOT, S_ARROW = ">", "*", "->"

BANNER = [
    r"  ____ _ _   _   _       _     ",
    r" / ___(_) |_| | | |_   _| |__  ",
    r"| |  _| | __| |_| | | | | '_ \ ",
    r"| |_| | | |_|  _  | |_| | |_) |",
    r" \____|_|\__|_| |_|\__,_|_.__/ ",
]


def term_width():
    return max(40, min(shutil.get_terminal_size((72, 24)).columns, 78))


def clear_screen():
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def rule():
    print(DG + H * term_width() + X)


def header(text):
    print()
    rule()
    print(" %s%s%s%s" % (G, B, text.upper(), X))
    rule()


def step(n, total, text):
    print("\n%s%s[%d/%d]%s %s%s%s" % (G, B, n, total, X, W, text, X))


def success(msg):
    print("%s%s[ SUCCESS ]%s %s%s%s" % (G, B, X, G, msg, X))


def fail(msg):
    print("%s%s[ FAILED ]%s %s%s%s" % (R, B, X, R, msg, X))


def warn(msg):
    print("%s%s[ WARNING ]%s %s%s%s" % (Y, B, X, Y, msg, X))


def info(msg):
    print("%s%s[ INFO ]%s %s%s%s" % (W, B, X, W, msg, X))


def box(heading, lines, color):
    """Large notification box (full success / full error)."""
    import textwrap
    w = term_width()
    inner = w - 4
    print()
    print(color + TL + H * (w - 2) + TR + X)
    print("%s%s%s %s%s%s%s %s%s" % (color, V, X, color + B, heading.center(inner), X, color, V, X))
    print(color + V + " " * (w - 2) + V + X)
    for line in lines:
        wrapped = textwrap.wrap(line, inner) or [""]
        for part in wrapped:
            print("%s%s%s %s%s %s%s%s" % (color, V, X, W, part.ljust(inner), color, V, X))
    print(color + BL + H * (w - 2) + BR + X)
    print()


class Spinner:
    """Animated loading spinner with an optional live detail text."""

    def __init__(self, label):
        self.label = label
        self.detail = ""
        self._stop = threading.Event()
        self._thread = None
        self._tty = sys.stdout.isatty()

    def __enter__(self):
        if self._tty:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        else:
            print("  %s ..." % self.label, flush=True)
        return self

    def _run(self):
        i = 0
        while not self._stop.is_set():
            label, detail = self.label, self.detail
            line = "%s%s%s %s%s%s" % (G, SPIN[i % len(SPIN)], X, W, label, X)
            room = term_width() - len(label) - 6
            if detail and room > 8:
                detail = re.sub(r"[\x00-\x1f\x7f]", " ", detail)
                line += " %s%s%s" % (DIM, detail[:room], X)
            sys.stdout.write("\r\033[K" + line)
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.09)

    def update(self, label=None, detail=None):
        if label is not None:
            self.label = label
        if detail is not None:
            self.detail = detail

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        return False


class ProgressBar:
    def __init__(self, total):
        self.total = max(1, total)
        self.tty = sys.stdout.isatty()
        self.last_pct = -1

    def update(self, done, label=""):
        frac = min(1.0, done / float(self.total))
        pct = int(frac * 100)
        if self.tty:
            bw = max(10, min(30, term_width() - 34))
            filled = int(bw * frac)
            room = max(0, term_width() - bw - 14)
            line = "  %s%s%s%s%s %s%s%3d%%%s %s%s%s" % (
                G, S_FULL * filled, DG, S_EMPTY * (bw - filled), X, W, B, pct, X, DIM, label[:room], X)
            sys.stdout.write("\r\033[K" + line)
            sys.stdout.flush()
        elif pct // 10 != self.last_pct // 10 or done >= self.total:
            if pct != self.last_pct:
                print("  Progress: %d%% %s" % (pct, label))
        self.last_pct = pct

    def finish(self):
        if self.tty:
            sys.stdout.write("\n")
            sys.stdout.flush()


def startup_animation(animate):
    interactive = animate and sys.stdout.isatty()
    if interactive:
        clear_screen()
    print()
    for line in BANNER:
        print("%s%s%s%s" % (G, B, line, X))
        if interactive:
            time.sleep(0.07)
    title = "%s  v%s" % (APP_NAME, VERSION)
    if interactive:
        sys.stdout.write("  %s%s" % (W, B))
        for ch in title:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.015)
        print(X)
    else:
        print("  %s%s%s%s" % (W, B, title, X))
    print("  %s%s%s\n" % (DG, APP_TAGLINE, X))
    if interactive:
        steps = ["Loading modules", "Checking environment", "Preparing interface"]
        total = 30
        bar = ProgressBar(total)
        for i in range(total + 1):
            bar.update(i, steps[min(len(steps) - 1, i * len(steps) // (total + 1))])
            time.sleep(0.03)
        bar.finish()
        time.sleep(0.2)


# ============================================================================
# Input helpers
# ============================================================================
class UserExit(Exception):
    """Raised when stdin is closed (Ctrl+D / end of input)."""


try:
    import readline  # line editing (arrow keys, history) for path input
    _RL = readline is not None
except Exception:
    _RL = False


def _rl(text):
    if _RL and sys.stdin.isatty() and sys.stdout.isatty():
        return re.sub(r"(\033\[[0-9;]*m)", "\001\\1\002", text)
    return text


def ask(prompt, default=None):
    suffix = " %s[%s]%s" % (DIM, default, X) if default not in (None, "") else ""
    text = "%s%s%s%s %s%s%s " % (G, B, prompt, X, G + B, S_PROMPT, X)
    try:
        value = input(_rl(text.replace(prompt, prompt + suffix, 1)))
    except EOFError:
        print()
        raise UserExit()
    value = value.strip()
    if not value and default is not None:
        return default
    return value


def ask_secret(prompt):
    try:
        return getpass.getpass("%s%s%s%s %s " % (G, B, prompt, X, S_PROMPT)).strip()
    except EOFError:
        print()
        raise UserExit()


def confirm(prompt, default=None):
    """Y/N question. default=None forces an explicit y or n."""
    hint = "[y/n]" if default is None else ("[Y/n]" if default else "[y/N]")
    while True:
        value = ask("%s %s" % (prompt, hint)).lower()
        if not value and default is not None:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        warn("Please answer with y or n.")


def pause():
    try:
        ask("Press Enter to return to the menu")
    except UserExit:
        pass


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


# ============================================================================
# Configuration & secure token storage
# ============================================================================
def _config_dir():
    override = os.environ.get("GHM_CONFIG_DIR")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "github-manager")


CONFIG_DIR = _config_dir()
TOKEN_FILE = os.path.join(CONFIG_DIR, "token")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        ensure_config_dir()
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def save_token(token):
    ensure_config_dir()
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    os.chmod(TOKEN_FILE, 0o600)


def load_token():
    try:
        with open(TOKEN_FILE, "r") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def delete_token():
    try:
        os.remove(TOKEN_FILE)
        return True
    except OSError:
        return False


_SECRETS = []


def register_secret(token):
    basic = base64.b64encode(("x-access-token:" + token).encode()).decode()
    for s in (token, basic):
        if s and s not in _SECRETS:
            _SECRETS.append(s)


def scrub(text):
    for s in _SECRETS:
        text = text.replace(s, "***")
    return text


# ============================================================================
# GitHub REST API (urllib only - nothing to pip install)
# ============================================================================
def _resolve_api_url():
    url = os.environ.get("GHM_API_URL", "").strip().rstrip("/")
    if not url:
        return "https://api.github.com"
    parsed = urllib.parse.urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme == "https" or (parsed.scheme == "http" and local):
        return url  # GitHub Enterprise (https) or a local test server
    return "https://api.github.com"


API_URL = _resolve_api_url()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _explain(status, message, errors):
    low = (message or "").lower()
    if status == 401:
        return "Authentication failed: the token is invalid, expired or revoked."
    if status == 403:
        if "rate limit" in low:
            return "GitHub API rate limit reached. Wait a few minutes and try again."
        return "Access denied: %s (the token may lack the required permission)." % (message or "forbidden")
    if status == 404:
        return "Not found, or the token has no access to it."
    if status == 422:
        detail = ""
        if isinstance(errors, list):
            detail = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
        return "GitHub rejected the request: %s %s" % (message or "validation failed", detail)
    return "GitHub API error %s: %s" % (status, message or "unknown error")


def api_request(method, path, token, payload=None, params=None, timeout=30):
    url = API_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        message, errors = "", None
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
            message, errors = body.get("message", ""), body.get("errors")
        except Exception:
            pass
        raise ApiError(exc.code, _explain(exc.code, message, errors)) from None
    except urllib.error.URLError as exc:
        raise ApiError(0, "Network error: %s" % getattr(exc, "reason", exc)) from None
    except OSError as exc:
        raise ApiError(0, "Network error: %s" % exc) from None
    if not raw:
        return None, resp_headers
    try:
        return json.loads(raw.decode("utf-8")), resp_headers
    except ValueError:
        raise ApiError(0, "GitHub returned an unreadable response.") from None


def fetch_repos(token, spinner=None):
    repos, page = [], 1
    while page <= 50:
        body, _ = api_request("GET", "/user/repos", token, params={
            "per_page": 100, "page": page, "sort": "updated",
            "affiliation": "owner,collaborator,organization_member"})
        if not body:
            break
        repos.extend(body)
        if spinner:
            spinner.update(detail="%d repositories" % len(repos))
        if len(body) < 100:
            break
        page += 1
    return repos


class Session:
    def __init__(self):
        self.token = None
        self.user = None
        self.repos = None

    @property
    def logged_in(self):
        return bool(self.token and self.user)

    @property
    def login(self):
        return (self.user or {}).get("login", "")


# ============================================================================
# Environment checks (first launch + menu option)
# ============================================================================
def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def storage_ok():
    path = os.path.join(os.path.expanduser("~"), "storage", "shared")
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def git_version():
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def install_package(pkg):
    if not shutil.which("pkg"):
        fail("The 'pkg' command was not found. Install '%s' manually with your package manager." % pkg)
        return False
    info("Running: pkg install -y %s" % pkg)
    try:
        rc = subprocess.call(["pkg", "install", "-y", pkg])
    except OSError as exc:
        fail("Could not run pkg: %s" % exc)
        return False
    return rc == 0


def offer_install(pkg, reason):
    """Ask permission before installing a missing package."""
    warn("%s is missing. %s" % (pkg, reason))
    if not is_termux():
        info("Not running inside Termux - please install '%s' with your package manager." % pkg)
        return False
    if confirm("Install '%s' now with 'pkg install %s'?" % (pkg, pkg), default=True):
        if install_package(pkg):
            success("'%s' installed." % pkg)
            return True
        fail("Installation of '%s' failed. Try: pkg update && pkg install %s" % (pkg, pkg))
    else:
        warn("Skipped installing '%s'." % pkg)
    return False


def network_check():
    """Returns (ok, detail). Any HTTP answer from GitHub counts as reachable."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
    try:
        urllib.request.urlopen(req, timeout=10).close()
        return True, ""
    except urllib.error.HTTPError:
        return True, ""
    except Exception as exc:
        return False, str(getattr(exc, "reason", exc))


def status_line(state, text):
    tag = {"ok": "%s%s[  OK  ]%s" % (G, B, X),
           "bad": "%s%s[ FAIL ]%s" % (R, B, X),
           "warn": "%s%s[ WARN ]%s" % (Y, B, X)}[state]
    print("  %s %s" % (tag, text))


def check_environment():
    header("System & dependency check")
    problems = 0

    # Python
    v = sys.version_info
    if v >= (3, 8):
        status_line("ok", "Python %d.%d.%d" % v[:3])
    else:
        status_line("bad", "Python %d.%d is too old (3.8+ required)" % v[:2])
        problems += 1
        if is_termux():
            offer_install("python", "Python 3.8 or newer is required.")

    # Git
    with Spinner("Looking for git"):
        time.sleep(0.2)
        gv = git_version() if shutil.which("git") else None
    if gv:
        status_line("ok", "git %d.%d" % gv)
    else:
        status_line("bad", "git is not installed (needed for uploads)")
        if offer_install("git", "It is required to stage, commit and push."):
            gv = git_version()
            status_line("ok" if gv else "bad", "git re-check")
        problems += 0 if gv else 1

    # Network + TLS
    with Spinner("Contacting GitHub"):
        ok, detail = network_check()
    if ok:
        status_line("ok", "GitHub reachable (%s)" % API_URL)
    else:
        status_line("bad", "Cannot reach GitHub: %s" % detail)
        problems += 1
        if "CERTIFICATE_VERIFY_FAILED" in detail and is_termux():
            if offer_install("ca-certificates", "TLS certificates are needed for HTTPS."):
                ok, detail = network_check()
                status_line("ok" if ok else "bad", "GitHub re-check")
        else:
            info("Check your internet connection (Wi-Fi / mobile data) and try again.")

    # Storage permission
    if is_termux():
        if storage_ok():
            status_line("ok", "Internal storage access granted (~/storage/shared)")
        else:
            status_line("warn", "Internal storage access not granted")
            warn("Without it the app cannot read /sdcard folders.")
            if confirm("Run 'termux-setup-storage' now? (Android will ask for permission)", default=True):
                if shutil.which("termux-setup-storage"):
                    subprocess.call(["termux-setup-storage"])
                    for _ in range(20):
                        if storage_ok():
                            break
                        time.sleep(0.5)
                    if storage_ok():
                        status_line("ok", "Internal storage access granted")
                    else:
                        status_line("warn", "Still no access - tap 'Allow' in the Android dialog, then re-run this check")
                        problems += 1
                else:
                    fail("termux-setup-storage not found. Run: pkg install termux-tools")
                    problems += 1
            else:
                warn("Skipped storage permission.")
    else:
        status_line("warn", "Not running in Termux - storage permission check skipped")

    # Config directory
    try:
        ensure_config_dir()
        probe = os.path.join(CONFIG_DIR, ".write-test")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        status_line("ok", "Config folder writable (%s)" % CONFIG_DIR)
    except OSError as exc:
        status_line("bad", "Config folder not writable: %s" % exc)
        problems += 1

    print()
    if problems == 0:
        success("All checks passed. Everything is ready.")
    else:
        warn("%d issue(s) found. Features that depend on them may not work." % problems)
    return problems


def ensure_git():
    if shutil.which("git") and git_version():
        return True
    fail("git is required for uploading but is not installed.")
    if offer_install("git", "It is required to stage, commit and push."):
        return bool(shutil.which("git"))
    return False


# ============================================================================
# Authentication
# ============================================================================
def verify_token(token):
    user, headers = api_request("GET", "/user", token)
    if not isinstance(user, dict) or "login" not in user:
        raise ApiError(0, "GitHub returned unexpected account data.")
    return user, headers.get("X-OAuth-Scopes")


def auto_login(sess):
    token = load_token()
    if not token:
        return
    register_secret(token)
    try:
        with Spinner("Verifying saved token"):
            user, _ = verify_token(token)
    except ApiError as exc:
        if exc.status == 401:
            warn("Saved token is no longer valid and was removed.")
            delete_token()
        else:
            warn("Could not verify the saved token (%s). Use option 1 to log in." % exc.message)
        return
    sess.token, sess.user = token, user
    success("Welcome back, %s!" % user["login"])


def action_login(sess):
    header("Login / Switch account")
    print("  %sCreate a token at: github.com/settings/tokens%s" % (W, X))
    print("  %sClassic token: tick the 'repo' scope (add 'delete_repo' to delete repos).%s" % (W, X))
    print("  %sFine-grained token: Contents = Read and write (Administration for create/delete).%s\n" % (W, X))

    env_token = os.environ.get("GITHUB_TOKEN", "").strip()
    for attempt in range(3):
        token = ""
        if env_token and attempt == 0 and confirm("Use the token from the GITHUB_TOKEN environment variable?", default=True):
            token = env_token
        else:
            token = ask_secret("Paste your token (input is hidden)")
        if not token:
            warn("No token entered.")
            continue
        if not re.fullmatch(r"[A-Za-z0-9_\-.]+", token):
            fail("That does not look like a GitHub token (unexpected characters).")
            continue
        register_secret(token)
        try:
            with Spinner("Verifying token with GitHub"):
                user, scopes = verify_token(token)
        except ApiError as exc:
            fail(exc.message)
            continue
        sess.token, sess.user, sess.repos = token, user, None
        success("Logged in as %s%s" % (user["login"], " (%s)" % user["name"] if user.get("name") else ""))
        if scopes is not None and not ({"repo", "public_repo"} & {s.strip() for s in scopes.split(",")}):
            warn("This token has no 'repo' scope - uploads and private repositories will fail.")
        if confirm("Save the token on this device for next time? (stored with owner-only permissions)", default=False):
            try:
                save_token(token)
                success("Token saved to %s (chmod 600)." % TOKEN_FILE)
            except OSError as exc:
                fail("Could not save the token: %s" % exc)
        return True
    fail("Login failed after 3 attempts.")
    return False


def ensure_login(sess):
    if sess.logged_in:
        return True
    warn("You are not logged in yet.")
    return bool(action_login(sess))


def action_logout(sess):
    header("Log out")
    had_saved = os.path.exists(TOKEN_FILE)
    sess.token, sess.user, sess.repos = None, None, None
    if had_saved:
        if delete_token():
            success("Saved token removed from this device.")
        else:
            fail("Could not delete %s - remove it manually." % TOKEN_FILE)
    success("Logged out.")


# ============================================================================
# Repository browsing
# ============================================================================
def load_repos(sess, force=False):
    if sess.repos is not None and not force:
        return True
    try:
        with Spinner("Fetching your repositories from GitHub") as sp:
            sess.repos = fetch_repos(sess.token, sp)
    except ApiError as exc:
        fail(exc.message)
        return False
    return True


def pick_repo(sess):
    """Interactive repository chooser. Returns a repo dict or None."""
    if not load_repos(sess):
        return None
    flt, query, page, per = "all", "", 0, 20
    while True:
        repos = sess.repos
        view = [r for r in repos
                if (flt == "all" or (flt == "public") == (not r.get("private")))
                and query.lower() in r["full_name"].lower()]
        pages = max(1, (len(view) + per - 1) // per)
        page = max(0, min(page, pages - 1))
        n_pub = sum(1 for r in repos if not r.get("private"))
        header("Your repositories")
        print("  %sTotal %d  |  Public %d  |  Private %d  |  Filter: %s%s%s%s\n" % (
            W, len(repos), n_pub, len(repos) - n_pub, G, B, flt.upper() + (" '%s'" % query if query else ""), X))
        if not view:
            warn("No repositories match.")
        width = term_width() - 20
        for i, r in enumerate(view[page * per:(page + 1) * per], start=page * per + 1):
            tag = "%s[PRIVATE]%s" % (Y, X) if r.get("private") else "%s[PUBLIC ]%s" % (G, X)
            extra = " %s(archived)%s" % (DIM, X) if r.get("archived") else ""
            print("  %s%3d.%s %s %s%s%s%s" % (G, i, X, tag, W, r["full_name"][:width], X, extra))
        print("\n  %sPage %d/%d%s" % (DIM, page + 1, pages, X))
        print("  %sNumber = select | N/P = next/prev | /text = search | F = filter | R = refresh | Q = cancel%s" % (DIM, X))
        raw = ask("Repository")
        low = raw.lower()
        if low in ("q", "quit", "cancel", "0"):
            return None
        if low == "n":
            page += 1
        elif low == "p":
            page -= 1
        elif low == "f":
            flt = {"all": "public", "public": "private", "private": "all"}[flt]
            page = 0
        elif low == "r":
            load_repos(sess, force=True)
            page = 0
        elif raw.startswith("/"):
            query, page = raw[1:].strip(), 0
        elif raw.isdigit() and 1 <= int(raw) <= len(view):
            return view[int(raw) - 1]
        else:
            warn("Invalid choice.")


def show_repo_details(sess, repo):
    header(repo["full_name"])
    vis = "Private" if repo.get("private") else "Public"
    rows = [
        ("Visibility", vis + (" (archived)" if repo.get("archived") else "")),
        ("Description", repo.get("description") or "-"),
        ("Default branch", repo.get("default_branch") or "-"),
        ("Language", repo.get("language") or "-"),
        ("Size", human_size((repo.get("size") or 0) * 1024)),
        ("Stars / Forks", "%s / %s" % (repo.get("stargazers_count", 0), repo.get("forks_count", 0))),
        ("Last push", repo.get("pushed_at") or "-"),
        ("Web URL", repo.get("html_url") or "-"),
    ]
    for key, value in rows:
        print("  %s%-15s%s %s%s%s" % (G, key, X, W, value, X))
    try:
        with Spinner("Loading branches"):
            branches, _ = api_request("GET", "/repos/%s/branches" % repo["full_name"], sess.token,
                                      params={"per_page": 30})
        names = [b["name"] for b in (branches or [])]
        print("  %s%-15s%s %s%s%s" % (G, "Branches", X, W, ", ".join(names) if names else "(empty repository)", X))
    except ApiError:
        pass


def action_browse(sess):
    if not ensure_login(sess):
        return
    repo = pick_repo(sess)
    if not repo:
        return
    show_repo_details(sess, repo)
    print()
    choice = ask("U = upload a folder to this repository, Enter = back", default="")
    if choice.lower() == "u":
        action_upload(sess, repo)


# ============================================================================
# Create / delete repository
# ============================================================================
def action_create(sess):
    if not ensure_login(sess):
        return
    header("Create a new repository")
    while True:
        name = ask("Repository name (q to cancel)")
        if name.lower() == "q":
            return
        if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name) and name not in (".", "..") and not name.endswith(".git"):
            break
        fail("Use only letters, digits, '.', '-' and '_' (max 100 characters).")
    description = ask("Description (optional)", default="")
    private = ask("Visibility: 1 = Private, 2 = Public", default="1") != "2"
    auto_init = confirm("Initialize with a README file?", default=False)
    try:
        with Spinner("Creating %s on GitHub" % name):
            repo, _ = api_request("POST", "/user/repos", sess.token, payload={
                "name": name, "description": description, "private": private, "auto_init": auto_init})
    except ApiError as exc:
        if exc.status == 422:
            fail("Could not create the repository - the name may already exist. %s" % exc.message)
        else:
            fail(exc.message)
        return
    sess.repos = None
    box("REPOSITORY CREATED", [
        "Name: %s" % repo["full_name"],
        "Visibility: %s" % ("Private" if repo.get("private") else "Public"),
        "URL: %s" % repo["html_url"]], G)
    if confirm("Upload a folder to this repository now?", default=False):
        action_upload(sess, repo)


def action_delete(sess):
    if not ensure_login(sess):
        return
    header("Delete a repository")
    warn("Deleting a repository is PERMANENT and cannot be undone.")
    repo = pick_repo(sess)
    if not repo:
        return
    print()
    warn("You are about to permanently delete %s" % repo["full_name"])
    typed = ask("Type the full repository name to confirm (or press Enter to cancel)", default="")
    if typed != repo["full_name"]:
        info("Names did not match - nothing was deleted.")
        return
    try:
        with Spinner("Deleting %s" % repo["full_name"]):
            api_request("DELETE", "/repos/%s" % repo["full_name"], sess.token)
    except ApiError as exc:
        fail(exc.message)
        if exc.status in (403, 404):
            info("Deleting needs the 'delete_repo' scope (classic) or Administration permission (fine-grained).")
        return
    sess.repos = None
    success("Repository %s was deleted." % repo["full_name"])


# ============================================================================
# Folder scanning & numbered selection
# ============================================================================
@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    files: int
    size: int


@dataclass
class FileItem:
    src: str
    rel: str
    size: int


def count_tree(path, spinner=None):
    files = size = 0
    for root, dirs, names in os.walk(path, followlinks=False, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if d != ".git" and not os.path.islink(os.path.join(root, d))]
        for name in names:
            if name == ".git":
                continue
            fp = os.path.join(root, name)
            try:
                if os.path.isfile(fp):
                    files += 1
                    size += os.path.getsize(fp)
            except OSError:
                pass
        if spinner:
            spinner.update(detail="%d files" % files)
    return files, size


def scan_level(path):
    names = sorted(os.listdir(path), key=lambda n: n.lower())
    entries = []
    with Spinner("Scanning " + path) as sp:
        for name in names:
            if name == ".git":
                continue
            p = os.path.join(path, name)
            try:
                if os.path.isdir(p):
                    files, size = count_tree(p, sp)
                    entries.append(Entry(name, p, True, files, size))
                elif os.path.isfile(p):
                    entries.append(Entry(name, p, False, 1, os.path.getsize(p)))
            except OSError:
                continue
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def parse_selection(text, count):
    indices = []
    for token in [t for t in re.split(r"[,\s]+", text) if t]:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a > b:
            a, b = b, a
        if a < 1 or b > count:
            return None
        indices.extend(range(a, b + 1))
    return indices or None


def effective_selection(selected):
    dirs = [p for p, e in selected.items() if e.is_dir]
    keep = []
    for p, e in selected.items():
        if any(p != d and p.startswith(d.rstrip(os.sep) + os.sep) for d in dirs):
            continue
        keep.append(e)
    return sorted(keep, key=lambda e: e.path)


def browse_and_select(root):
    stack, selected, cache, page, per = [root], {}, {}, 0, 25
    while True:
        cur = stack[-1]
        if cur not in cache:
            try:
                cache[cur] = scan_level(cur)
            except OSError as exc:
                fail("Cannot read folder: %s" % (exc.strerror or exc))
                if len(stack) == 1:
                    return None
                stack.pop()
                continue
        entries = cache[cur]
        pages = max(1, (len(entries) + per - 1) // per)
        page = max(0, min(page, pages - 1))

        header("Select files & folders")
        print("  %sFolder:%s %s%s%s\n" % (G, X, W, cur, X))
        if not entries:
            warn("This folder is empty.")
        namew = term_width() - 36
        for i, e in enumerate(entries[page * per:(page + 1) * per], start=page * per + 1):
            mark = "%s[x]%s" % (G, X) if e.path in selected else "[ ]"
            kind = "%sDIR %s" % (G, X) if e.is_dir else "FILE"
            name = e.name + ("/" if e.is_dir else "")
            if len(name) > namew:
                name = name[:namew - 1] + "~"
            info_txt = "%s files, %s" % (e.files, human_size(e.size)) if e.is_dir else human_size(e.size)
            print("  %3d. %s %s %s%-*s%s %s%s%s" % (i, mark, kind, W, namew, name, X, DIM, info_txt, X))
        eff = effective_selection(selected)
        print("\n  %sPage %d/%d  |  Selected: %d item(s), %d file(s), %s%s" % (
            DIM, page + 1, pages, len(eff), sum(e.files for e in eff), human_size(sum(e.size for e in eff)), X))
        print("  %sNumbers: 1,3,5-8 toggle | A = SELECT ALL here | C = clear | O 2 = open folder 2%s" % (DIM, X))
        print("  %sB = back | N/P = page | D = done (continue) | Q = cancel%s" % (DIM, X))

        raw = ask("Selection")
        low = raw.lower()
        if low in ("q", "quit", "cancel"):
            return None
        if low in ("d", "done"):
            if selected:
                return selected
            warn("Nothing selected yet.")
        elif low in ("a", "all"):
            if entries:
                for e in entries:
                    selected[e.path] = e
                success("Selected all %d item(s) in this folder." % len(entries))
            else:
                warn("Nothing to select here.")
        elif low in ("c", "clear"):
            selected.clear()
            info("Selection cleared.")
        elif low == "n":
            page += 1
        elif low == "p":
            page -= 1
        elif low in ("b", "back", "u", "up"):
            if len(stack) > 1:
                stack.pop()
                page = 0
            else:
                warn("Already at the top folder you entered.")
        elif re.fullmatch(r"o(?:pen)?\s*\d+", low):
            idx = int(re.search(r"\d+", low).group())
            if 1 <= idx <= len(entries) and entries[idx - 1].is_dir:
                stack.append(entries[idx - 1].path)
                page = 0
            else:
                warn("Item %d is not a folder you can open." % idx)
        else:
            indices = parse_selection(low, len(entries))
            if indices is None:
                warn("Invalid selection. Use numbers like 1,3,5-8 or A for all.")
                continue
            for i in indices:
                e = entries[i - 1]
                if e.path in selected:
                    del selected[e.path]
                else:
                    selected[e.path] = e


def collect_files(entries, root):
    files, too_big, seen = [], [], set()
    stats = {"unreadable": 0}

    def add(src):
        rel = os.path.relpath(src, root).replace(os.sep, "/")
        if rel in seen:
            return
        seen.add(rel)
        try:
            size = os.path.getsize(src)
        except OSError:
            stats["unreadable"] += 1
            return
        if size >= MAX_FILE_BYTES:
            too_big.append((rel, size))
        else:
            files.append(FileItem(src, rel, size))

    with Spinner("Collecting files") as sp:
        for e in entries:
            if not e.is_dir:
                add(e.path)
                continue
            for r, dirs, names in os.walk(e.path, followlinks=False, onerror=lambda err: None):
                dirs[:] = [d for d in dirs if d != ".git" and not os.path.islink(os.path.join(r, d))]
                for name in names:
                    fp = os.path.join(r, name)
                    if name != ".git" and os.path.isfile(fp):
                        add(fp)
                sp.update(detail="%d files" % len(files))
    return files, too_big, stats["unreadable"]


def clean_repo_path(text):
    text = text.strip().replace("\\", "/").strip("/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    for p in parts:
        if p == ".." or p.lower() == ".git" or re.search(r"[\x00-\x1f]", p):
            raise ValueError("Folder path may not contain '..', '.git' or control characters.")
    return "/".join(parts)


def valid_branch(name):
    if not name or name.startswith("-"):
        return False
    try:
        return subprocess.run(["git", "check-ref-format", "--branch", name],
                              capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ask_source_path():
    default = os.path.join(os.path.expanduser("~"), "storage", "shared")
    if not os.path.isdir(default):
        default = os.getcwd()
    print("  %sExamples:  ~/storage/shared/Download   /sdcard/MyProject   ~/myfolder%s" % (DIM, X))
    while True:
        raw = ask("Folder to upload from (q to cancel)", default=default)
        if raw.lower() == "q":
            return None
        raw = raw.strip().strip("'\"")
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
        if not os.path.exists(path):
            fail("Path does not exist: %s" % path)
        elif not os.path.isdir(path):
            fail("That is a file. Enter the folder that contains it, then select the file.")
        elif not os.access(path, os.R_OK | os.X_OK):
            fail("No permission to read: %s" % path)
            if is_termux() and not storage_ok():
                warn("Storage permission is missing. Run menu option 6 (System check) to grant it.")
        else:
            return path


# ============================================================================
# Git engine (real git; token passed via environment, never stored in repo)
# ============================================================================
_ENV_CONFIG = None


def _git_supports_env_config():
    global _ENV_CONFIG
    if _ENV_CONFIG is None:
        v = git_version()
        _ENV_CONFIG = bool(v and v >= (2, 31))
    return _ENV_CONFIG


def build_git_cmd(args, token=None, url=None):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["LC_ALL"] = "C"
    pairs = [("credential.helper", ""), ("http.postBuffer", "524288000"), ("core.quotepath", "false")]
    if token and url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            basic = base64.b64encode(("x-access-token:" + token).encode()).decode()
            scope = "%s://%s/" % (parsed.scheme, parsed.netloc)
            pairs.append(("http.%s.extraheader" % scope, "Authorization: Basic " + basic))
    if _git_supports_env_config():
        env["GIT_CONFIG_COUNT"] = str(len(pairs))
        for i, (k, val) in enumerate(pairs):
            env["GIT_CONFIG_KEY_%d" % i] = k
            env["GIT_CONFIG_VALUE_%d" % i] = val
        cmd = ["git"] + list(args)
    else:
        cmd = ["git"]
        for k, val in pairs:
            cmd += ["-c", "%s=%s" % (k, val)]
        cmd += list(args)
    return cmd, env


def run_git(args, cwd=None, token=None, url=None, label=None):
    """Run git, optionally with a live spinner. Returns (returncode, stdout, stderr)."""
    cmd, env = build_git_cmd(args, token, url)
    spinner = Spinner(label) if label else None
    out_buf, err_buf = [], []
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        return 127, "", "git could not be started: %s" % exc

    def pump(stream, buf, live):
        while True:
            chunk = os.read(stream.fileno(), 4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", "replace")
            buf.append(text)
            if live and spinner:
                segs = [s for s in re.split(r"[\r\n]+", text) if s.strip()]
                if segs:
                    spinner.update(detail=scrub(segs[-1].strip()))

    threads = [threading.Thread(target=pump, args=(proc.stdout, out_buf, False), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err_buf, True), daemon=True)]
    if spinner:
        spinner.__enter__()
    try:
        for t in threads:
            t.start()
        proc.wait()
        for t in threads:
            t.join()
    except BaseException:
        proc.kill()
        raise
    finally:
        if spinner:
            spinner.__exit__(None, None, None)
    return proc.returncode, scrub("".join(out_buf)), scrub("".join(err_buf))


def describe_git_error(err):
    low = err.lower()
    if "authentication failed" in low or "invalid username" in low or "401" in low:
        return "GitHub rejected the token. Log in again with a valid token that has the 'repo' scope."
    if "protected branch" in low or "gh006" in low:
        return "The branch is protected. Upload to a different branch (e.g. a new branch name) and open a pull request."
    if "repository not found" in low or "403" in low or "permission to" in low:
        return "No write access to this repository. Check the token's permissions and the repository owner."
    if "could not resolve host" in low or "unable to access" in low and "resolve" in low:
        return "Network problem: cannot reach GitHub. Check your connection and try again."
    if "gh001" in low or "file size" in low or "larger than" in low:
        return "A file is too large for GitHub (limit 100 MB per file). Remove it and retry."
    if "rpc failed" in low or "early eof" in low or "timed out" in low or "http 408" in low or "http 500" in low:
        return "The connection dropped during transfer. Try again on a stable connection or upload fewer files at once."
    lines = [ln.strip() for ln in err.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-3:]) if lines else "Unknown git error."


class UploadError(Exception):
    pass


def push_branch(work, token, url, branch):
    """Push HEAD to the branch. If the remote moved, rebase once and retry."""
    refspec = "HEAD:refs/heads/%s" % branch
    rc, out, err = run_git(["push", "--progress", "origin", refspec], cwd=work, token=token, url=url,
                           label="Pushing to GitHub")
    if rc == 0:
        return
    low = err.lower()
    if "non-fast-forward" in low or "fetch first" in low or "[rejected]" in low:
        warn("The remote branch has new commits. Rebasing your upload on top of them...")
        rc, _, err2 = run_git(["pull", "--rebase", "--no-edit", "origin", branch], cwd=work, token=token,
                              url=url, label="Syncing with remote")
        if rc != 0:
            run_git(["rebase", "--abort"], cwd=work)
            rc, _, _ = run_git(["fetch", "--unshallow", "origin"], cwd=work, token=token, url=url,
                               label="Fetching full history")
            rc, _, err2 = run_git(["pull", "--rebase", "--no-edit", "origin", branch], cwd=work, token=token,
                                  url=url, label="Syncing with remote")
            if rc != 0:
                run_git(["rebase", "--abort"], cwd=work)
                raise UploadError("Could not merge with the newer remote commits automatically. "
                                  "Nothing was overwritten on GitHub. Run the upload again. (%s)" % describe_git_error(err2))
        rc, out, err = run_git(["push", "--progress", "origin", refspec], cwd=work, token=token, url=url,
                               label="Pushing to GitHub")
        if rc == 0:
            return
    raise UploadError(describe_git_error(err))


def unique_name(path, taken):
    stem, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = "%s_%d%s" % (stem, n, ext)
        if not os.path.lexists(cand) and cand not in taken:
            return cand
        n += 1


def perform_upload(sess, repo, branch, dest, files, message):
    """Clone -> copy -> stage -> commit -> push. Returns a result dict."""
    token, url = sess.token, repo["clone_url"]
    user = sess.user
    tmp = tempfile.mkdtemp(prefix="ghm-")
    work = os.path.join(tmp, "repo")
    total_steps = 6
    try:
        # 1 ---- clone
        step(1, total_steps, "Cloning repository (existing content is preserved)")
        rc, _, err = run_git(["clone", "--depth", "1", "--progress", "--branch", branch, url, work],
                             token=token, url=url, label="Cloning " + repo["full_name"])
        if rc != 0:
            if re.search(r"remote branch .* not found", err, re.I):
                shutil.rmtree(work, ignore_errors=True)
                rc, _, err = run_git(["clone", "--progress", url, work], token=token, url=url,
                                     label="Cloning " + repo["full_name"])
            if rc != 0:
                raise UploadError(describe_git_error(err))
            rc_head, _, _ = run_git(["rev-parse", "--verify", "HEAD"], cwd=work)
            if rc_head != 0:
                run_git(["symbolic-ref", "HEAD", "refs/heads/" + branch], cwd=work)
                info("Repository is empty - your upload becomes the first commit on '%s'." % branch)
            else:
                rc_co, _, err_co = run_git(["checkout", "-b", branch], cwd=work)
                if rc_co != 0:
                    raise UploadError("Could not create branch '%s': %s" % (branch, err_co.strip()))
                info("Branch '%s' does not exist yet - it will be created from the default branch." % branch)
        success("Repository ready")

        # 2 ---- identity
        step(2, total_steps, "Preparing commit identity")
        login = user.get("login", "user")
        name = user.get("name") or login
        email = "%s+%s@users.noreply.github.com" % (user.get("id"), login) if user.get("id") else \
            "%s@users.noreply.github.com" % login
        for key, val in (("user.name", name), ("user.email", email), ("core.fileMode", "false"),
                         ("core.autocrlf", "false"), ("commit.gpgsign", "false")):
            run_git(["config", key, val], cwd=work)
        success("Commit author: %s <%s>" % (name, email))

        # 3 ---- copy
        step(3, total_steps, "Copying selected files into the repository")
        real_work = os.path.realpath(work)
        plan, conflicts, unchanged, blocked = [], [], 0, []
        for f in files:
            rel = (dest + "/" + f.rel) if dest else f.rel
            tgt = os.path.join(work, *rel.split("/"))
            if not os.path.realpath(tgt).startswith(real_work + os.sep):
                blocked.append(rel)
                continue
            if os.path.lexists(tgt):
                if os.path.islink(tgt) or os.path.isdir(tgt):
                    blocked.append(rel)
                    continue
                if filecmp.cmp(f.src, tgt, shallow=False):
                    unchanged += 1
                    continue
                conflicts.append([f, rel, tgt])
                continue
            plan.append([f, rel, tgt])

        if conflicts:
            warn("%d file(s) already exist in the repository with DIFFERENT content:" % len(conflicts))
            for _, rel, _ in conflicts[:8]:
                print("    %s- %s%s" % (Y, rel, X))
            if len(conflicts) > 8:
                print("    %s... and %d more%s" % (Y, len(conflicts) - 8, X))
            print("  %s[S] Skip existing (safest)   [R] Keep both (rename new files)   [O] Overwrite   [C] Cancel%s" % (W, X))
            while True:
                choice = ask("Conflict policy", default="s").lower()
                if choice in ("s", "r", "o", "c"):
                    break
                warn("Choose S, R, O or C.")
            if choice == "c":
                raise UploadError("Upload cancelled. Nothing was changed on GitHub.")
            if choice == "o":
                plan.extend(conflicts)
            elif choice == "r":
                taken = set(item[2] for item in plan)
                for item in conflicts:
                    new_tgt = unique_name(item[2], taken)
                    taken.add(new_tgt)
                    item[2] = new_tgt
                    item[1] = os.path.relpath(new_tgt, work).replace(os.sep, "/")
                    plan.append(item)
            else:
                info("Skipping %d existing file(s)." % len(conflicts))
        if unchanged:
            info("%d file(s) are already identical in the repository and were skipped." % unchanged)
        for rel in blocked[:5]:
            warn("Skipped (path blocked by an existing folder/link): " + rel)

        written, failed = [], []
        if plan:
            bar = ProgressBar(len(plan))
            for i, (f, rel, tgt) in enumerate(plan, 1):
                try:
                    os.makedirs(os.path.dirname(tgt), exist_ok=True)
                    shutil.copyfile(f.src, tgt)
                    written.append(rel)
                except OSError as exc:
                    failed.append((rel, exc.strerror or str(exc)))
                bar.update(i, os.path.basename(f.src))
            bar.finish()
        for rel, why in failed[:5]:
            warn("Could not copy %s (%s)" % (rel, why))
        if len(failed) > 5:
            warn("... and %d more copy errors." % (len(failed) - 5))
        if not written:
            if plan and failed:
                raise UploadError("No file could be copied.")
            return {"nothing": True, "repo": repo, "branch": branch}
        success("%d file(s) copied" % len(written))

        # 4 ---- stage
        step(4, total_steps, "Staging changes (git add)")
        rc, _, err = run_git(["add", "-A"], cwd=work, label="Staging files")
        if rc != 0:
            raise UploadError("git add failed: " + err.strip())
        rc, out, _ = run_git(["diff", "--cached", "--name-only", "-z"], cwd=work)
        staged = set(p for p in out.split("\0") if p)
        ignored = [w for w in written if w not in staged]
        if ignored:
            warn("%d file(s) were not staged because the repository's .gitignore excludes them." % len(ignored))
        if not staged:
            return {"nothing": True, "repo": repo, "branch": branch}
        success("%d file(s) staged" % len(staged))

        # 5 ---- commit
        step(5, total_steps, "Creating commit")
        rc, out, err = run_git(["commit", "-m", message], cwd=work, label="Committing")
        if rc != 0:
            if "nothing to commit" in (out + err).lower():
                return {"nothing": True, "repo": repo, "branch": branch}
            raise UploadError("git commit failed: " + (err.strip() or out.strip()))
        _, sha, _ = run_git(["rev-parse", "--short", "HEAD"], cwd=work)
        sha = sha.strip()
        success("Commit %s created" % sha)

        # 6 ---- push
        step(6, total_steps, "Pushing to GitHub (git push)")
        push_branch(work, token, url, branch)
        success("Push completed")
        return {"nothing": False, "repo": repo, "branch": branch, "sha": sha, "count": len(staged),
                "dest": dest}
    finally:
        def _onerror(func, path, _exc):
            try:
                os.chmod(path, 0o700)
                func(path)
            except OSError:
                pass
        shutil.rmtree(tmp, onerror=_onerror)


def action_upload(sess, repo=None):
    if not ensure_login(sess):
        return
    if not ensure_git():
        return
    header("Upload folder to repository")
    if repo is None:
        repo = pick_repo(sess)
        if not repo:
            return
    if repo.get("archived"):
        fail("%s is archived (read-only). Unarchive it on GitHub first." % repo["full_name"])
        return
    perms = repo.get("permissions")
    if isinstance(perms, dict) and perms.get("push") is False:
        warn("Your account does not seem to have write access to %s." % repo["full_name"])
        if not confirm("Try anyway?", default=False):
            return
    print("\n  %sTarget:%s %s%s%s (%s)\n" % (G, X, W, repo["full_name"], X, "private" if repo.get("private") else "public"))

    root = ask_source_path()
    if not root:
        return
    selection = browse_and_select(root)
    if not selection:
        info("Upload cancelled.")
        return
    entries = effective_selection(selection)
    files, too_big, unreadable = collect_files(entries, root)

    for rel, size in too_big[:5]:
        warn("Skipped (over GitHub's 100 MB file limit): %s [%s]" % (rel, human_size(size)))
    if len(too_big) > 5:
        warn("... and %d more oversized files skipped." % (len(too_big) - 5))
    if unreadable:
        warn("%d file(s) could not be read and were skipped." % unreadable)
    if not files:
        fail("There are no uploadable files in your selection.")
        return
    total = sum(f.size for f in files)
    big = [f for f in files if f.size >= WARN_FILE_BYTES]
    if big:
        warn("%d file(s) are over 50 MB; GitHub will warn about them." % len(big))
    if total >= WARN_TOTAL_BYTES:
        warn("Total size is %s - large uploads can time out on mobile data. Wi-Fi is recommended." % human_size(total))

    print()
    while True:
        try:
            dest = clean_repo_path(ask("Destination folder inside the repo (Enter = repository root)", default=""))
            break
        except ValueError as exc:
            fail(str(exc))
    default_branch = repo.get("default_branch") or "main"
    while True:
        branch = ask("Branch to push to", default=default_branch)
        if valid_branch(branch):
            break
        fail("'%s' is not a valid branch name." % branch)
    message = ask("Commit message", default="Upload %d file(s) via GitHub Repository Manager" % len(files))

    box("UPLOAD SUMMARY", [
        "Repository : %s (%s)" % (repo["full_name"], "private" if repo.get("private") else "public"),
        "Branch     : %s" % branch,
        "Destination: %s" % (dest + "/" if dest else "(repository root)"),
        "Files      : %d  (%s)" % (len(files), human_size(total)),
        "Source     : %s" % root,
        "Existing repository content is preserved."], G)
    if not confirm("Upload these files to GitHub now?"):
        info("Upload cancelled. Nothing was changed.")
        return

    try:
        result = perform_upload(sess, repo, branch, dest, files, message)
    except UploadError as exc:
        box("UPLOAD FAILED", [str(exc), "Nothing was lost: your local files are untouched."], R)
        return
    if result.get("nothing"):
        warn("Nothing new to upload - the repository already contains these files.")
        return
    url = repo["html_url"] + "/tree/" + branch + (("/" + dest) if dest else "")
    sess.repos = None
    box("UPLOAD COMPLETE - ALL FILES PUSHED", [
        "%d file(s) are now on GitHub." % result["count"],
        "Repository: %s" % repo["full_name"],
        "Branch: %s   Commit: %s" % (branch, result["sha"]),
        "View: %s" % url], G)


# ============================================================================
# Main menu
# ============================================================================
def render_menu(sess):
    clear_screen()
    w = term_width()
    print()
    print("%s%s%s%s%s" % (G, TL, H * (w - 2), TR, X))
    print("%s%s%s %s%s%s %s%s%s" % (G, V, X, W + B, "MAIN MENU".center(w - 4), X, G, V, X))
    print("%s%s%s%s%s" % (G, BL, H * (w - 2), BR, X))
    if sess.logged_in:
        print("  %s%s%s Logged in as %s%s%s" % (G, S_DOT, X, G + B, sess.login, X))
    else:
        print("  %s%s%s %sNot logged in%s" % (Y, S_DOT, X, Y, X))
    print()
    items = [
        ("1", "Login / Switch account"),
        ("2", "Browse my repositories (public & private)"),
        ("3", "Upload folder to a repository"),
        ("4", "Create a new repository"),
        ("5", "Delete a repository"),
        ("6", "System & dependency check"),
        ("7", "Log out & remove saved token"),
        ("0", "Exit"),
    ]
    for key, text in items:
        print("  %s%s[%s]%s %s%s%s" % (G, B, key, X, W, text, X))
    print()


def main_menu(sess):
    actions = {
        "1": action_login,
        "2": action_browse,
        "3": action_upload,
        "4": action_create,
        "5": action_delete,
        "6": lambda s: check_environment(),
        "7": action_logout,
    }
    while True:
        render_menu(sess)
        try:
            choice = ask("Choose an option")
        except KeyboardInterrupt:
            print()
            return
        if choice in ("0", "q", "exit", "quit"):
            return
        action = actions.get(choice)
        if not action:
            warn("Please enter a number from the menu.")
            time.sleep(0.8)
            continue
        try:
            action(sess)
        except KeyboardInterrupt:
            print()
            warn("Cancelled. Returning to the menu.")
        except UserExit:
            raise
        except Exception as exc:  # last-resort safety net: never crash to a traceback
            fail("Unexpected error: %s" % scrub(str(exc)))
            if os.environ.get("GHM_DEBUG"):
                raise
        try:
            pause()
        except KeyboardInterrupt:
            print()


def parse_args(argv):
    p = argparse.ArgumentParser(prog="github.py", description=APP_NAME + " - " + APP_TAGLINE)
    p.add_argument("--version", action="version", version="%s %s" % (APP_NAME, VERSION))
    p.add_argument("--no-anim", action="store_true", help="skip the startup animation")
    p.add_argument("--check", action="store_true", help="run the system & dependency check and exit")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sess = Session()
    try:
        startup_animation(not args.no_anim and not os.environ.get("GHM_FAST"))
        settings = load_settings()
        if args.check:
            return 0 if check_environment() == 0 else 1
        if not settings.get("first_run_done"):
            header("First launch - permissions & dependencies")
            info("Checking what this app needs. You will be asked before anything is installed.")
            check_environment()
            settings["first_run_done"] = True
            save_settings(settings)
            pause()
        auto_login(sess)
        main_menu(sess)
    except (UserExit, KeyboardInterrupt):
        print()
    print("\n%s%sThanks for using %s. Goodbye!%s\n" % (G, B, APP_NAME, X))
    return 0


if __name__ == "__main__":
    sys.exit(main())
