import os
import requests
from flask import Flask, redirect, request, session, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Used to encrypt session data

# ── Xero credentials (loaded from .env) ──────────────────────────────────────
CLIENT_ID     = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("XERO_REDIRECT_URI")
TENANT_ID     = os.getenv("XERO_TENANT_ID")

XERO_AUTH_URL  = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE  = "https://api.xero.com/api.xro/2.0"

SCOPES = "openid profile email accounting.transactions accounting.settings offline_access"


# ── STEP 1: Start OAuth 2.0 Login ────────────────────────────────────────────
@app.route("/login")
def login():
    auth_url = (
        f"{XERO_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES}"
        f"&state=xero_auth"
    )
    return redirect(auth_url)


# ── STEP 2: Handle Callback & Exchange Code for Token ────────────────────────
@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "No code returned from Xero"}), 400

    response = requests.post(
        XERO_TOKEN_URL,
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
    )

    if response.status_code != 200:
        return jsonify({"error": "Token exchange failed", "details": response.json()}), 400

    tokens = response.json()
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens["refresh_token"]

    return jsonify({"message": "Authenticated successfully! ✅", "token_type": tokens["token_type"]})


# ── Helper: Get Tenant ID from Xero dynamically ──────────────────────────────
@app.route("/connections")
def get_connections():
    response = requests.get(
        "https://api.xero.com/connections",
        headers={
            "Authorization": f"Bearer {session.get('access_token')}",
            "Accept": "application/json",
        }
    )
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch connections", "details": response.json()}), response.status_code
    connections = response.json()
    # Store the first tenant ID in session
    if connections:
        session["tenant_id"] = connections[0]["tenantId"]
    return jsonify(connections)


# ── Helper: Build headers for every Xero API call ────────────────────────────
def xero_headers():
    return {
        "Authorization": f"Bearer {session.get('access_token')}",
        "Xero-Tenant-Id": session.get("tenant_id", TENANT_ID),
        "Accept": "application/json",
    }


# ── STEP 3a: Accounts Endpoint ────────────────────────────────────────────────
@app.route("/accounts")
def get_accounts():
    response = requests.get(f"{XERO_API_BASE}/Accounts", headers=xero_headers())
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch accounts", "details": response.json()}), response.status_code
    return jsonify(response.json())


# ── STEP 3b: Bank Transactions Endpoint ──────────────────────────────────────
@app.route("/bank-transactions")
def get_bank_transactions():
    response = requests.get(f"{XERO_API_BASE}/BankTransactions", headers=xero_headers())
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch bank transactions", "details": response.json()}), response.status_code
    return jsonify(response.json())


# ── STEP 3c: Invoices Endpoint ────────────────────────────────────────────────
@app.route("/invoices")
def get_invoices():
    response = requests.get(f"{XERO_API_BASE}/Invoices", headers=xero_headers())
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch invoices", "details": response.json()}), response.status_code
    return jsonify(response.json())


# ── STEP 4: Token Refresh (call this when access token expires) ───────────────
@app.route("/refresh-token")
def refresh_token():
    response = requests.post(
        XERO_TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": session.get("refresh_token"),
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    if response.status_code != 200:
        return jsonify({"error": "Token refresh failed", "details": response.json()}), 400

    tokens = response.json()
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens["refresh_token"]
    return jsonify({"message": "Token refreshed successfully! ✅"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)