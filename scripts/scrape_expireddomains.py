"""Scrape expireddomains.net and POST to Lovable webhook."""
import hashlib, hmac, json, os, re, sys, time
import requests
from playwright.sync_api import sync_playwright

LIST_URL = (
    "https://www.expireddomains.net/deleted-com-domains/"
    "?ftlds[]=2&fwhois=22&fadult=1&flimit=200&fbl_filter=10&fbl_min=1"
)

EXPIRED_USER = os.environ["EXPIRED_USER"]
EXPIRED_PASS = os.environ["EXPIRED_PASS"]
OTP_CODE = os.environ.get("OTP_CODE", "").strip()
WEBHOOK_URL = os.environ["LOVABLE_WEBHOOK_URL"]
WEBHOOK_SECRET = os.environ["LOVABLE_WEBHOOK_SECRET"]
JOB_ID = os.environ.get("JOB_ID") or None
RUN_URL = os.environ.get("GITHUB_RUN_URL") or None


def post(payload):
    body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(WEBHOOK_URL, data=body,
        headers={"Content-Type": "application/json", "x-webhook-signature": sig},
        timeout=30)
    print("webhook:", r.status_code, r.text[:200])
    r.raise_for_status()


def to_int(s):
    if not s: return 0
    s = re.sub(r"[^\d\-]", "", str(s))
    if not s or s == "-": return 0
    try: return int(s)
    except ValueError: return 0


def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto("https://member.expireddomains.net/login/", wait_until="domcontentloaded")
        page.fill('input[name="login"]', EXPIRED_USER)
        page.fill('input[name="password"]', EXPIRED_PASS)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        if page.locator('input[name*="otp"], input[name*="code"], input[name*="token"]').count() > 0:
            if not OTP_CODE:
                raise RuntimeError("OTP required but OTP_CODE empty")
            page.locator('input[name*="otp"], input[name*="code"], input[name*="token"]').first.fill(OTP_CODE)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
        page.goto(LIST_URL, wait_until="networkidle")
        rows = []
        for tr in page.locator("table.base1 tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells: continue
            try: domain = cells[1].split()[0].lower()
            except IndexError: continue
            if "." not in domain: continue
            bl = to_int(cells[2]) if len(cells) > 2 else 0
            dp = to_int(cells[3]) if len(cells) > 3 else 0
            age = to_int(cells[4]) if len(cells) > 4 else 0
            stem, _, tld = domain.partition(".")
            rows.append({"domain": domain, "tld": tld, "length": len(stem),
                "backlinks": bl, "domain_pop": dp, "age": age})
        browser.close()
        return rows


def main():
    try:
        rows = scrape()
        print(f"scraped {len(rows)} rows")
        post({"job_id": JOB_ID, "github_run_url": RUN_URL, "status": "completed", "rows": rows})
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        try:
            post({"job_id": JOB_ID, "github_run_url": RUN_URL, "status": "failed",
                "error": str(e)[:1000], "rows": []})
        except Exception as e2:
            print("failed to report error:", e2, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
