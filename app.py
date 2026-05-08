import os
import requests
import mysql.connector
from flask import Flask, redirect, request, session, render_template_string
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ── Credentials ───────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("XERO_REDIRECT_URI")

XERO_AUTH_URL  = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE  = "https://api.xero.com/api.xro/2.0"
SCOPES = "openid profile email accounting.transactions accounting.settings offline_access"

# ── DB Connection ─────────────────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host     = os.getenv("DB_HOST"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        database = os.getenv("DB_NAME"),
    )

# ── Create Tables ─────────────────────────────────────────────────────────────
def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id   VARCHAR(100) PRIMARY KEY,
            code         VARCHAR(50),
            name         VARCHAR(255),
            class        VARCHAR(50),
            type         VARCHAR(50),
            status       VARCHAR(50),
            description  TEXT,
            tax_type     VARCHAR(50)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id     VARCHAR(100) PRIMARY KEY,
            invoice_number VARCHAR(100),
            contact_name   VARCHAR(255),
            date           VARCHAR(50),
            due_date       VARCHAR(50),
            total          DECIMAL(15,2),
            status         VARCHAR(50)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            transaction_id VARCHAR(100) PRIMARY KEY,
            date           VARCHAR(50),
            contact_name   VARCHAR(255),
            reference      VARCHAR(255),
            total          DECIMAL(15,2),
            type           VARCHAR(50),
            status         VARCHAR(50)
        )
    """)
    db.commit()
    cur.close()
    db.close()

# ── Sync Xero Data to MySQL ───────────────────────────────────────────────────
def sync_to_db(accounts, invoices, bank_transactions):
    db = get_db()
    cur = db.cursor()

    # Accounts
    cur.execute("DELETE FROM accounts")
    for a in accounts:
        cur.execute("""
            INSERT INTO accounts (account_id, code, name, class, type, status, description, tax_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            a.get("AccountID"), a.get("Code"), a.get("Name"),
            a.get("Class"), a.get("Type"), a.get("Status"),
            a.get("Description", ""), a.get("TaxType", "")
        ))

    # Invoices
    cur.execute("DELETE FROM invoices")
    for inv in invoices:
        cur.execute("""
            INSERT INTO invoices (invoice_id, invoice_number, contact_name, date, due_date, total, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            inv.get("InvoiceID"), inv.get("InvoiceNumber"),
            inv.get("Contact", {}).get("Name", ""),
            inv.get("DateString", ""), inv.get("DueDateString", ""),
            inv.get("Total", 0), inv.get("Status", "")
        ))

    # Bank Transactions
    cur.execute("DELETE FROM bank_transactions")
    for bt in bank_transactions:
        cur.execute("""
            INSERT INTO bank_transactions (transaction_id, date, contact_name, reference, total, type, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            bt.get("BankTransactionID"),
            bt.get("DateString", ""),
            bt.get("Contact", {}).get("Name", ""),
            bt.get("Reference", ""),
            bt.get("Total", 0),
            bt.get("Type", ""),
            bt.get("Status", "")
        ))

    db.commit()
    cur.close()
    db.close()

# ── Load Data from MySQL ──────────────────────────────────────────────────────
def load_from_db():
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM accounts")
    accounts = cur.fetchall()
    cur.execute("SELECT * FROM invoices")
    invoices = cur.fetchall()
    cur.execute("SELECT * FROM bank_transactions")
    bank_transactions = cur.fetchall()
    cur.close()
    db.close()
    return accounts, invoices, bank_transactions

# ── HTML Templates ────────────────────────────────────────────────────────────
LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>Chairtime | Connect Xero</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; display: flex; justify-content: center; align-items: center; height: 100vh; }
    .card { background: #1e293b; border-radius: 16px; padding: 48px; text-align: center; box-shadow: 0 25px 50px rgba(0,0,0,0.4); max-width: 400px; width: 90%; }
    .logo { font-size: 32px; font-weight: 800; color: #13b5ea; margin-bottom: 8px; }
    .subtitle { color: #94a3b8; margin-bottom: 32px; font-size: 15px; }
    .btn { display: inline-block; background: #13b5ea; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px; transition: background 0.2s; }
    .btn:hover { background: #0ea5d8; }
    .note { margin-top: 20px; color: #475569; font-size: 13px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">☁ Chairtime</div>
    <div class="subtitle">Connect your Xero account to get started</div>
    <a href="/login" class="btn">Connect with Xero</a>
    <div class="note">You'll be redirected to Xero to approve access</div>
  </div>
</body>
</html>
"""

DASHBOARD_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>Chairtime | Dashboard</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
    header { background: #1e293b; padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; }
    .logo { font-size: 22px; font-weight: 800; color: #13b5ea; }
    .org { color: #94a3b8; font-size: 14px; }
    .header-right { display: flex; align-items: center; gap: 16px; }
    .sync-btn { background: #22c55e; color: white; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px; }
    .sync-btn:hover { background: #16a34a; }
    .container { max-width: 1200px; margin: 32px auto; padding: 0 24px; }
    .sync-msg { background: #052e16; color: #4ade80; padding: 12px 20px; border-radius: 8px; margin-bottom: 24px; font-size: 14px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 40px; }
    .card { background: #1e293b; border-radius: 12px; padding: 24px; border-left: 4px solid #13b5ea; }
    .card.green { border-color: #22c55e; }
    .card.purple { border-color: #a855f7; }
    .card.orange { border-color: #f97316; }
    .card-label { color: #94a3b8; font-size: 13px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
    .card-value { font-size: 36px; font-weight: 700; color: #f1f5f9; }
    .card-sub { font-size: 13px; color: #64748b; margin-top: 4px; }
    .section { margin-bottom: 40px; }
    .section-title { font-size: 18px; font-weight: 700; margin-bottom: 16px; color: #f1f5f9; display: flex; align-items: center; gap: 8px; }
    .badge { background: #334155; color: #94a3b8; font-size: 12px; padding: 2px 8px; border-radius: 12px; font-weight: 500; }
    .table-wrap { background: #1e293b; border-radius: 12px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { background: #0f172a; color: #94a3b8; padding: 12px 16px; text-align: left; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    td { padding: 12px 16px; border-top: 1px solid #334155; color: #cbd5e1; }
    tr:hover td { background: #263548; }
    .pill { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .pill-asset { background: #0c4a6e; color: #38bdf8; }
    .pill-liability { background: #450a0a; color: #f87171; }
    .pill-equity { background: #1a1a2e; color: #a78bfa; }
    .pill-revenue { background: #052e16; color: #4ade80; }
    .pill-expense { background: #431407; color: #fb923c; }
    .pill-active { background: #052e16; color: #4ade80; }
    .empty { padding: 40px; text-align: center; color: #475569; }
  </style>
</head>
<body>
  <header>
    <div class="logo">☁ Chairtime</div>
    <div class="header-right">
      <div class="org">Connected: <strong style="color:#e2e8f0">{{ org_name }}</strong></div>
      <a href="/resync" class="sync-btn">🔄 Resync from Xero</a>
    </div>
  </header>

  <div class="container">
    {% if synced %}
    <div class="sync-msg">✅ Data successfully synced from Xero and saved to MySQL!</div>
    {% endif %}

    <div class="cards">
      <div class="card">
        <div class="card-label">Total Accounts</div>
        <div class="card-value">{{ accounts|length }}</div>
        <div class="card-sub">Chart of Accounts</div>
      </div>
      <div class="card green">
        <div class="card-label">Invoices</div>
        <div class="card-value">{{ invoices|length }}</div>
        <div class="card-sub">All invoices</div>
      </div>
      <div class="card purple">
        <div class="card-label">Bank Transactions</div>
        <div class="card-value">{{ bank_transactions|length }}</div>
        <div class="card-sub">All transactions</div>
      </div>
      <div class="card orange">
        <div class="card-label">Active Accounts</div>
        <div class="card-value">{{ accounts|selectattr('status', 'equalto', 'ACTIVE')|list|length }}</div>
        <div class="card-sub">Status: Active</div>
      </div>
    </div>

    <!-- Accounts Table -->
    <div class="section">
      <div class="section-title">📒 Chart of Accounts <span class="badge">{{ accounts|length }}</span></div>
      <div class="table-wrap">
        {% if accounts %}
        <table>
          <thead><tr><th>Code</th><th>Name</th><th>Class</th><th>Type</th><th>Status</th></tr></thead>
          <tbody>
            {% for a in accounts %}
            <tr>
              <td>{{ a.get('code', '—') }}</td>
              <td>{{ a.get('name', '—') }}</td>
              <td><span class="pill pill-{{ a.get('class', '')|lower }}">{{ a.get('class', '—') }}</span></td>
              <td>{{ a.get('type', '—') }}</td>
              <td><span class="pill pill-active">{{ a.get('status', '—') }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}<div class="empty">No accounts found.</div>{% endif %}
      </div>
    </div>

    <!-- Invoices Table -->
    <div class="section">
      <div class="section-title">🧾 Invoices <span class="badge">{{ invoices|length }}</span></div>
      <div class="table-wrap">
        {% if invoices %}
        <table id="invoices-table">
          <thead>
            <tr>
              <th onclick="sortTable(0)" style="cursor:pointer">Invoice # ↕</th>
              <th onclick="sortTable(1)" style="cursor:pointer">Contact ↕</th>
              <th onclick="sortTable(2)" style="cursor:pointer">Date ↕</th>
              <th onclick="sortTable(3)" style="cursor:pointer">Due Date ↕</th>
              <th onclick="sortTable(4)" style="cursor:pointer">Amount ↕</th>
              <th onclick="sortTable(5)" style="cursor:pointer">Status ↕</th>
            </tr>
          </thead>
          <tbody>
            {% for inv in invoices %}
            <tr>
              <td>{{ inv.get('invoice_number', '—') }}</td>
              <td>{{ inv.get('contact_name', '—') }}</td>
              <td>{{ inv.get('date', '—') }}</td>
              <td>{{ inv.get('due_date', '—') }}</td>
              <td>${{ inv.get('total', 0) }}</td>
              <td><span class="pill pill-active">{{ inv.get('status', '—') }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}<div class="empty">No invoices found.</div>{% endif %}
      </div>
    </div>

    <script>
      var sortDir = {};
      function sortTable(col) {
        var tbl = document.getElementById("invoices-table");
        var tbody = tbl.tBodies[0];
        var rows = [];
        for (var i = 0; i < tbody.rows.length; i++) {
          rows.push(tbody.rows[i]);
        }
        if (sortDir[col] === undefined) sortDir[col] = true;
        else sortDir[col] = !sortDir[col];
        var asc = sortDir[col];
        rows.sort(function(a, b) {
          var aVal = a.cells[col].innerText.trim();
          var bVal = b.cells[col].innerText.trim();
          if (col === 4) {
            aVal = parseFloat(aVal.replace('$', '')) || 0;
            bVal = parseFloat(bVal.replace('$', '')) || 0;
            return asc ? aVal - bVal : bVal - aVal;
          }
          if (aVal < bVal) return asc ? -1 : 1;
          if (aVal > bVal) return asc ? 1 : -1;
          return 0;
        });
        for (var i = 0; i < rows.length; i++) {
          tbody.appendChild(rows[i]);
        }
      }
    </script>

    <!-- Bank Transactions Table -->
    <div class="section">
      <div class="section-title">🏦 Bank Transactions <span class="badge">{{ bank_transactions|length }}</span></div>
      <div class="table-wrap">
        {% if bank_transactions %}
        <table>
          <thead><tr><th>Date</th><th>Contact</th><th>Reference</th><th>Amount</th><th>Type</th><th>Status</th></tr></thead>
          <tbody>
            {% for bt in bank_transactions %}
            <tr>
              <td>{{ bt.get('date', '—') }}</td>
              <td>{{ bt.get('contact_name', '—') }}</td>
              <td>{{ bt.get('reference', '—') }}</td>
              <td>${{ bt.get('total', 0) }}</td>
              <td>{{ bt.get('type', '—') }}</td>
              <td><span class="pill pill-active">{{ bt.get('status', '—') }}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}<div class="empty">No bank transactions found.</div>{% endif %}
      </div>
    </div>
  </div>
</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(LOGIN_PAGE)

@app.route("/login")
def login():
    auth_url = (
        f"{XERO_AUTH_URL}?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES}"
        f"&state=xero_auth"
    )
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "No code returned from Xero", 400

    response = requests.post(
        XERO_TOKEN_URL,
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    if response.status_code != 200:
        return f"Token exchange failed: {response.json()}", 400

    tokens = response.json()
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens["refresh_token"]

    conn = requests.get(
        "https://api.xero.com/connections",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Accept": "application/json"}
    ).json()
    if conn:
        preferred = next((c for c in conn if "Demo Company" in c["tenantName"]), conn[0])
        session["tenant_id"] = preferred["tenantId"]
        session["org_name"]  = preferred["tenantName"]

    return redirect("/sync")

def xero_headers():
    return {
        "Authorization": f"Bearer {session.get('access_token')}",
        "Xero-Tenant-Id": session.get("tenant_id"),
        "Accept": "application/json",
    }

@app.route("/sync")
def sync():
    headers = xero_headers()
    accounts          = requests.get(f"{XERO_API_BASE}/Accounts", headers=headers).json().get("Accounts", [])
    invoices          = requests.get(f"{XERO_API_BASE}/Invoices", headers=headers).json().get("Invoices", [])
    bank_transactions = requests.get(f"{XERO_API_BASE}/BankTransactions", headers=headers).json().get("BankTransactions", [])

    init_db()
    sync_to_db(accounts, invoices, bank_transactions)
    return redirect("/dashboard?synced=1")

@app.route("/resync")
def resync():
    return redirect("/sync")

@app.route("/dashboard")
def dashboard():
    accounts, invoices, bank_transactions = load_from_db()
    return render_template_string(
        DASHBOARD_PAGE,
        org_name          = session.get("org_name", "Unknown"),
        accounts          = accounts,
        invoices          = invoices,
        bank_transactions = bank_transactions,
        synced            = request.args.get("synced"),
    )

@app.route("/refresh-token")
def refresh_token():
    response = requests.post(
        XERO_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": session.get("refresh_token")},
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    if response.status_code != 200:
        return f"Token refresh failed: {response.json()}", 400
    tokens = response.json()
    session["access_token"]  = tokens["access_token"]
    session["refresh_token"] = tokens["refresh_token"]
    return redirect("/dashboard")

if __name__ == "__main__":
    init_db()  # Create tables on startup
    app.run(debug=True, port=5000)