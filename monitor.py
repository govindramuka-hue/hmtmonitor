import requests
import json
import os
import re
import firebase_admin
from firebase_admin import credentials, firestore
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

BREVO_API_KEY = os.environ["BREVO_API_KEY"]
SENDER_EMAIL  = os.environ["SENDER_EMAIL"]
SENDER_NAME   = "HMT Kohinoor Alert"

service_account = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── SITE 2: hmtwatches.store (API based) ─────────────────────────────────────
def fetch_site2():
    url = "https://smartpos.amazon.in/api-unauthenticated/resources/external/catalog/products?groupVariants=true"
    payload = {"filter": {"division": None, "isBestSeller": None}, "limit": 100, "offset": 0, "shopId": 48236}
    headers = {"Content-Type": "application/json", "Origin": "https://www.hmtwatches.store", "Referer": "https://www.hmtwatches.store/"}
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    products = [p for p in r.json() if "kohinoor" in p.get("name", "").lower()]
    print(f"Site 2: Found {len(products)} Kohinoor products")
    for p in products:
        avail = p.get("buyingOptions", {}).get("singlePurchase", {}).get("availability", {})
        if avail.get("inStock") or avail.get("isBuyable"):
            return True, "https://www.hmtwatches.store/collection/c757ecc9-31e2-4cf7-bcb1-9b29f5c57c41/Kohinoor"
    return False, None

# ── SITE 1: hmtwatches.in (HTML based) ───────────────────────────────────────
def fetch_site1():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    r = requests.get("https://www.hmtwatches.in", headers=headers, timeout=15)
    page = r.text
    # Find all product blocks that contain Kohinoor
    # Each product block looks like: product name ... RS. XXXX ... (optionally "Out Of Stock")
    # We find product_overview links near "Kohinoor" and check if "Out Of Stock" follows before the next product
    product_blocks = re.split(r'product_overview\?id=', page)
    kohinoor_available = False
    for block in product_blocks:
        if "kohinoor" in block.lower():
            # Check if this block has Out Of Stock before the next price mention
            first_500 = block[:500]
            if "Out Of Stock" not in first_500:
                kohinoor_available = True
                print(f"Site 1: Found available Kohinoor product")
                break
    return kohinoor_available, "https://www.hmtwatches.in" if kohinoor_available else None

def get_last_state():
    doc = db.collection("state").document("drop_status").get()
    if doc.exists:
        return doc.to_dict()
    return {"site1": False, "site2": False}

def save_state(site1, site2):
    db.collection("state").document("drop_status").set({"site1": site1, "site2": site2})

def log_drop(site, url):
    from datetime import datetime, timezone
    db.collection("drops").add({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "site": site,
        "product": "HMT Kohinoor",
        "url": url
    })

def get_subscribers():
    return [doc.to_dict().get("email") for doc in db.collection("subscribers").stream() if doc.to_dict().get("email")]

def send_alerts(emails, site1_url, site2_url):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
    subject = "🚨 HMT Kohinoor is IN STOCK NOW!"
    links = ""
    if site2_url:
        links += f'<a href="{site2_url}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:10px;">Buy on HMT Store</a>'
    if site1_url:
        links += f'<a href="{site1_url}" style="background:#333;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;">Buy on HMT Official</a>'
    html = f"""<h2>HMT Kohinoor Drop Alert</h2>
    <p>The HMT Kohinoor watch is <strong>available right now</strong>. Act fast — it sells out quickly!</p>
    <p style="margin-top:20px;">{links}</p>
    <p style="color:#888;font-size:12px;margin-top:20px;">You subscribed to HMT Kohinoor drop alerts.</p>"""
    for email in emails:
        try:
            api.send_transac_email(sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": email}],
                sender={"email": SENDER_EMAIL, "name": SENDER_NAME},
                subject=subject, html_content=html))
            print(f"Sent to {email}")
        except ApiException as e:
            print(f"Failed: {email} — {e}")

def main():
    print("Checking HMT Kohinoor stock on both sites...")

    try:
        site2_in_stock, site2_url = fetch_site2()
        print(f"Site 2 (hmtwatches.store): {'IN STOCK' if site2_in_stock else 'Out of Stock'}")
    except Exception as e:
        print(f"Site 2 failed: {e}")
        site2_in_stock, site2_url = False, None

    try:
        site1_in_stock, site1_url = fetch_site1()
        print(f"Site 1 (hmtwatches.in): {'IN STOCK' if site1_in_stock else 'Out of Stock'}")
    except Exception as e:
        print(f"Site 1 failed: {e}")
        site1_in_stock, site1_url = False, None

    last = get_last_state()
    new_drop_site1 = site1_in_stock and not last.get("site1", False)
    new_drop_site2 = site2_in_stock and not last.get("site2", False)

    if new_drop_site1 or new_drop_site2:
        print("DROP DETECTED — sending alerts!")
        if new_drop_site1:
            log_drop("hmtwatches.in", site1_url)
        if new_drop_site2:
            log_drop("hmtwatches.store", site2_url)
        subscribers = get_subscribers()
        print(f"Sending to {len(subscribers)} subscribers...")
        if subscribers:
            send_alerts(
                subscribers,
                site1_url if site1_in_stock else None,
                site2_url if site2_in_stock else None
            )
    else:
        print("No new drops detected.")

    save_state(site1_in_stock, site2_in_stock)
    print("Done.")

if __name__ == "__main__":
    main()
