import requests
import json
import os
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

def fetch_products():
    url = "https://smartpos.amazon.in/api-unauthenticated/resources/external/catalog/products?groupVariants=true"
    payload = {"filter": {"division": None, "isBestSeller": None}, "limit": 100, "offset": 0, "shopId": 48236}
    headers = {"Content-Type": "application/json", "Origin": "https://www.hmtwatches.store", "Referer": "https://www.hmtwatches.store/"}
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    return [p for p in r.json() if "kohinoor" in p.get("name", "").lower()]

def any_in_stock(products):
    for p in products:
        avail = p.get("buyingOptions", {}).get("singlePurchase", {}).get("availability", {})
        if avail.get("inStock") or avail.get("isBuyable"):
            return True
    return False

def get_last_state():
    doc = db.collection("state").document("drop_status").get()
    return doc.to_dict().get("was_in_stock", False) if doc.exists else False

def save_state(is_in_stock):
    db.collection("state").document("drop_status").set({"was_in_stock": is_in_stock})

def log_drop():
    from datetime import datetime, timezone
    db.collection("drops").add({"timestamp": datetime.now(timezone.utc).isoformat(), "site": "hmtwatches.store", "product": "HMT Kohinoor"})

def get_subscribers():
    return [doc.to_dict().get("email") for doc in db.collection("subscribers").stream() if doc.to_dict().get("email")]

def send_alerts(emails):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
    subject = "🚨 HMT Kohinoor is IN STOCK NOW!"
    html = """<h2>HMT Kohinoor Drop Alert</h2>
    <p>The HMT Kohinoor watch is <strong>available right now</strong>. Act fast!</p>
    <p>
      <a href="https://www.hmtwatches.store/collection/c757ecc9-31e2-4cf7-bcb1-9b29f5c57c41/Kohinoor" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;margin-right:10px;">Buy on HMT Store</a>
      <a href="https://www.hmtwatches.in" style="background:#333;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px;">Buy on HMT Official</a>
    </p>"""
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
    print("Checking HMT Kohinoor stock...")
    products = fetch_products()
    print(f"Found {len(products)} Kohinoor products")
    currently_in_stock = any_in_stock(products)
    was_in_stock = get_last_state()
    print(f"Was in stock: {was_in_stock} | Now: {currently_in_stock}")
    if currently_in_stock and not was_in_stock:
        print("DROP DETECTED — sending alerts!")
        log_drop()
        subscribers = get_subscribers()
        if subscribers:
            send_alerts(subscribers)
    save_state(currently_in_stock)
    print("Done.")

if __name__ == "__main__":
    main()
