"""Boutique: the service topology of Google's open-source "Online Boutique" microservices demo
(github.com/GoogleCloudPlatform/microservices-demo, Apache-2.0): 10 services + the Redis cart store.

The services and their call graph follow that project's architecture diagram. Everything else here is
OUR synthetic addition and is labelled as such: which services are monitored, teams, people, customers,
features and the incident history. The load generator is left out (it is a test client, not a service).
"""

SERVICES = {
    "frontend": ("edge", 1, "go", True, "Storefront"),
    "checkoutservice": ("api", 1, "go", True, "Checkout"),
    "cartservice": ("core", 1, "csharp", True, "Checkout"),
    "productcatalogservice": ("core", 1, "go", True, "Storefront"),
    "currencyservice": ("core", 1, "node", False, "Platform"),        # synthetic choice: no alerting on it
    "paymentservice": ("core", 1, "node", True, "Checkout"),
    "shippingservice": ("core", 2, "go", True, "Checkout"),
    "emailservice": ("core", 3, "python", True, "Platform"),
    "recommendationservice": ("core", 2, "python", True, "Storefront"),
    "adservice": ("core", 3, "java", True, "Storefront"),
    "redis-cart": ("data", 1, "redis", False, "Platform"),            # synthetic choice: no alerting on it
}

S = "sync"
DEPS = [(a, b, S) for a, bs in {
    "frontend": ["adservice", "cartservice", "checkoutservice", "currencyservice", "productcatalogservice",
                 "recommendationservice", "shippingservice"],
    "checkoutservice": ["cartservice", "currencyservice", "emailservice", "paymentservice",
                        "productcatalogservice", "shippingservice"],
    "recommendationservice": ["productcatalogservice"],
    "cartservice": ["redis-cart"],
}.items() for b in bs]

TEAMS = {"Storefront": "#storefront-oncall", "Checkout": "#checkout-oncall", "Platform": "#platform-oncall"}
IST, CET, PST = "Asia/Kolkata", "Europe/Berlin", "America/Los_Angeles"
PEOPLE = [
    ("Isha Rao", "isha", IST, "Storefront", True), ("Tom Fischer", "tom", CET, "Storefront", False),
    ("Grace Lee", "grace", PST, "Checkout", True), ("Kabir Shah", "kabir", IST, "Checkout", False),
    ("Nora Berg", "nora", CET, "Platform", True), ("Sam Ortiz", "sam", PST, "Platform", False),
]
FEATURES = {
    "Browse Catalog": ["frontend", "productcatalogservice", "currencyservice"],
    "Cart": ["frontend", "cartservice"],
    "Checkout": ["checkoutservice", "paymentservice", "shippingservice", "emailservice"],
    "Recommendations": ["recommendationservice", "adservice"],
}
CUSTOMER_NAMES = ["Hipster Goods", "Vintage Vinyl", "Urban Planters", "Brewcraft", "Lens & Co",
                  "Thread Lab", "Paper Trail", "Cast Iron Co"]
PATTERNS = [
    dict(key="redis_cart_oom", service="redis-cart", kind="config", occurrences=3, action="rollback",
         deploy="Lower redis-cart maxmemory and switch eviction policy",
         title="redis-cart evicting sessions, carts and checkout fail",
         summary="A config change lowered redis-cart memory; carts were evicted and cart and checkout calls failed. Fixed by rolling back the config.",
         fix="Roll back the redis-cart memory config", ttr=(5, 12)),
    dict(key="currency_rates_timeout", service="currencyservice", kind="code", occurrences=2, action="rollback",
         deploy="Switch currencyservice to the new rates provider client",
         title="currency conversion timeouts on every page",
         summary="A new rates client in currencyservice timed out; the frontend and checkout failed on price conversion. Fixed by rollback.",
         fix="Roll back the currencyservice rates client", ttr=(8, 15)),
]
CONFIG = dict(name="boutique", seed=3003, services=SERVICES, deps=DEPS, teams=TEAMS, people=PEOPLE,
              features=FEATURES, customers=CUSTOMER_NAMES, patterns=PATTERNS,
              generic_roots=["productcatalogservice", "paymentservice", "shippingservice", "redis-cart"],
              runbooks=["redis-cart", "currencyservice"], deploys_per_service_90d=12, n_generic_incidents=5)
