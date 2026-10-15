"""Acme Pay: a payments company, 30 services. Static topology; history is generated in history.py."""

# name: (layer, tier, language, monitored, team)
SERVICES = {
    "web-gateway": ("edge", 1, "go", True, "Edge"),
    "mobile-bff": ("edge", 1, "node", True, "Edge"),
    "partner-api": ("edge", 2, "java", True, "Edge"),
    "payments-api": ("api", 1, "java", True, "Payments"),
    "refunds-api": ("api", 2, "java", True, "Payments"),
    "orders-api": ("api", 1, "python", True, "Commerce"),
    "accounts-api": ("api", 1, "python", True, "Identity"),
    "payouts-api": ("api", 2, "java", True, "Payments"),
    "search-api": ("api", 3, "go", True, "Commerce"),
    "notifications-api": ("api", 3, "node", True, "Commerce"),
    "ledger-svc": ("core", 1, "java", True, "Ledger"),
    "fraud-svc": ("core", 1, "python", True, "Risk"),
    "pricing-svc": ("core", 2, "go", True, "Commerce"),
    "auth-svc": ("core", 1, "go", True, "Identity"),
    "risk-engine": ("core", 2, "python", True, "Risk"),
    "fx-rates": ("core", 3, "go", True, "Payments"),
    "kyc-svc": ("core", 2, "python", True, "Identity"),
    "audit-svc": ("core", 3, "java", True, "Ledger"),
    "settlement-svc": ("core", 2, "java", True, "Ledger"),
    "billing-svc": ("core", 2, "java", True, "Ledger"),
    "notif-worker": ("core", 3, "node", True, "Commerce"),
    "reporting-svc": ("core", 3, "python", True, "Ledger"),
    "ledger-db": ("data", 1, "postgres", False, "Ledger"),
    "orders-db": ("data", 1, "postgres", True, "Commerce"),
    "accounts-db": ("data", 1, "postgres", True, "Identity"),
    "redis-cache": ("data", 2, "redis", False, "Platform"),
    "kafka": ("data", 1, "kafka", False, "Platform"),
    "search-index": ("data", 3, "elasticsearch", True, "Commerce"),
    "fraud-store": ("data", 2, "cassandra", False, "Risk"),
    "audit-db": ("data", 3, "postgres", True, "Ledger"),
}

S, A = "sync", "async"
# (dependent, dependency, kind): "dependent breaks if dependency breaks"
DEPS = [(a, b, S) for a, bs in {
    "web-gateway": ["auth-svc", "payments-api", "orders-api", "refunds-api", "accounts-api", "search-api"],
    "mobile-bff": ["auth-svc", "payments-api", "accounts-api", "orders-api", "notifications-api"],
    "partner-api": ["auth-svc", "payments-api", "payouts-api"],
    "payments-api": ["ledger-svc", "fraud-svc", "pricing-svc", "auth-svc", "redis-cache"],
    "refunds-api": ["ledger-svc", "auth-svc", "orders-api"],
    "orders-api": ["orders-db", "pricing-svc", "auth-svc", "redis-cache"],
    "accounts-api": ["accounts-db", "kyc-svc", "auth-svc"],
    "payouts-api": ["ledger-svc", "settlement-svc", "auth-svc", "fx-rates"],
    "search-api": ["search-index", "auth-svc"],
    "notifications-api": ["auth-svc", "kafka"],
    "ledger-svc": ["ledger-db"],
    "fraud-svc": ["risk-engine", "fraud-store", "redis-cache"],
    "pricing-svc": ["fx-rates", "redis-cache"],
    "auth-svc": ["accounts-db", "redis-cache"],
    "risk-engine": ["fraud-store"],
    "kyc-svc": ["accounts-db"],
    "audit-svc": ["ledger-db", "audit-db"],
    "settlement-svc": ["ledger-svc", "ledger-db"],
    "billing-svc": ["ledger-svc", "pricing-svc"],
    "reporting-svc": ["ledger-db", "orders-db"],
}.items() for b in bs] + [(a, b, A) for a, b in [
    ("ledger-svc", "kafka"), ("notif-worker", "kafka"), ("reporting-svc", "kafka"),
    ("audit-svc", "kafka"), ("orders-api", "kafka"),
]]

TEAMS = {
    "Edge": "#edge-oncall", "Payments": "#payments-oncall", "Commerce": "#commerce-oncall",
    "Identity": "#identity-oncall", "Ledger": "#ledger-oncall", "Risk": "#risk-oncall",
    "Platform": "#platform-oncall",
}

IST, CET, PST = "Asia/Kolkata", "Europe/Berlin", "America/Los_Angeles"
# name, handle, tz, team, on_call
PEOPLE = [
    ("Aarav Mehta", "aarav", IST, "Edge", True), ("Lena Fischer", "lena", CET, "Edge", False),
    ("Priya Nair", "priya", IST, "Payments", True), ("Marco Rossi", "marco", CET, "Payments", False),
    ("Jordan Lee", "jordan", PST, "Payments", False), ("Ishaan Rao", "ishaan", IST, "Commerce", False),
    ("Hannah Weber", "hannah", CET, "Commerce", True), ("Tyler Brooks", "tyler", PST, "Commerce", False),
    ("Sofia Alvarez", "sofia", PST, "Identity", True), ("Kabir Shah", "kabir", IST, "Identity", False),
    ("Noah Becker", "noah", CET, "Ledger", True), ("Meera Iyer", "meera", IST, "Ledger", False),
    ("Chris Walker", "chris", PST, "Ledger", False), ("Anya Petrova", "anya", CET, "Risk", True),
    ("Dev Kapoor", "dev", IST, "Risk", False), ("Emma Clarke", "emma", PST, "Platform", True),
    ("Rahul Verma", "rahul", IST, "Platform", False), ("Felix Braun", "felix", CET, "Platform", False),
]

FEATURES = {
    "Checkout": ["payments-api", "orders-api", "pricing-svc", "fraud-svc", "web-gateway", "mobile-bff"],
    "Refunds": ["refunds-api", "ledger-svc"],
    "Payouts": ["payouts-api", "settlement-svc", "partner-api"],
    "Account Signup": ["accounts-api", "kyc-svc", "auth-svc"],
    "Search": ["search-api", "search-index"],
    "Notifications": ["notifications-api", "notif-worker"],
    "Invoicing": ["billing-svc", "pricing-svc"],
    "Reporting": ["reporting-svc"],
}

CUSTOMER_NAMES = [
    "Northwind Retail", "Contoso Travel", "Globe Air", "Bluebird Foods", "Kite Mobility", "Orbit Telecom",
    "Lumen Health", "Pioneer Bank", "Summit Outdoors", "Vertex Media", "Harbor Freight Co", "Zenith Games",
    "Maple Grocers", "Atlas Insurance", "Nimbus SaaS", "Cobalt Energy", "Fable Books", "Redwood Homes",
    "Tango Rides", "Quartz Labs", "Sparrow Pay", "Delta Ticketing", "Ember Fashion", "Willow Pharmacy", "Juno Streaming",
]

# Planted recurring patterns (History agent should find these).
PATTERNS = [
    dict(key="ledger_pool", service="ledger-db", kind="config", occurrences=4, action="rollback",
         deploy="Reduce ledger-db connection pool max_connections 200 -> 40",
         title="ledger-db connection pool exhausted",
         summary="Config change to ledger-db connection pool (max_connections) caused pool exhaustion; 5xx errors across the payments cluster. Fixed by rolling back the config deploy.",
         fix="Roll back the ledger-db connection pool config deploy", ttr=(5, 9)),
    dict(key="kafka_rebalance", service="kafka", kind="infra", occurrences=3, action="scale",
         deploy="Kafka partition rebalance after broker pool resize",
         title="kafka partition rebalance consumer lag",
         summary="Kafka partition rebalance left consumers behind; consumer lag grew on async dependents. Fixed by scaling consumers until the backlog drained.",
         fix="Scale up consumers and wait for the backlog to drain", ttr=(14, 25)),
    dict(key="auth_cert", service="auth-svc", kind="infra", occurrences=3, action="hotfix",
         deploy="Rotate auth-svc signing certificate",
         title="auth-svc certificate rotation failures",
         summary="Certificate rotation on auth-svc left some pods with the old certificate; authentication failures everywhere. Fixed by redeploying the certificate.",
         fix="Redeploy the auth-svc certificate to all pods", ttr=(8, 15)),
]

# Other incident flavours used to fill history to ~25.
GENERIC_ROOTS = ["redis-cache", "orders-db", "fraud-store", "pricing-svc", "search-index", "fx-rates",
                 "risk-engine", "accounts-db", "settlement-svc", "kyc-svc", "billing-svc", "payments-api"]

RUNBOOK_SERVICES = ["ledger-db", "kafka", "auth-svc", "redis-cache", "orders-db", "fraud-store", "payments-api"]

CONFIG = dict(name="acme", seed=1001, services=SERVICES, deps=DEPS, teams=TEAMS, people=PEOPLE,
              features=FEATURES, customers=CUSTOMER_NAMES, patterns=PATTERNS, generic_roots=GENERIC_ROOTS,
              runbooks=RUNBOOK_SERVICES, deploys_per_service_90d=15, n_generic_incidents=16)
