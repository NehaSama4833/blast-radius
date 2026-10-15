"""Globex Logistics: 15 services, deeper chains and a hub-and-spoke dispatch core (different shape from Acme)."""

SERVICES = {
    "customer-portal": ("edge", 1, "node", True, "Customer"),
    "driver-bff": ("edge", 1, "kotlin", True, "Dispatch"),
    "shipments-api": ("api", 1, "java", True, "Dispatch"),
    "tracking-api": ("api", 2, "go", True, "Customer"),
    "routing-api": ("api", 1, "python", True, "Dispatch"),
    "invoicing-api": ("api", 2, "java", True, "Customer"),
    "dispatch-svc": ("core", 1, "java", True, "Dispatch"),
    "eta-svc": ("core", 2, "python", True, "Dispatch"),
    "geo-svc": ("core", 2, "go", True, "Platform"),
    "id-svc": ("core", 1, "go", True, "Platform"),
    "ops-db": ("data", 1, "postgres", True, "Platform"),
    "geo-cache": ("data", 2, "redis", False, "Platform"),
    "event-bus": ("data", 1, "nats", False, "Platform"),
    "telemetry-store": ("data", 2, "clickhouse", False, "Platform"),
    "rates-db": ("data", 3, "postgres", True, "Customer"),
}

S, A = "sync", "async"
DEPS = [(a, b, S) for a, bs in {
    "customer-portal": ["id-svc", "shipments-api", "tracking-api", "invoicing-api"],
    "driver-bff": ["id-svc", "dispatch-svc", "routing-api"],
    "shipments-api": ["ops-db", "dispatch-svc", "id-svc"],
    "tracking-api": ["eta-svc", "telemetry-store", "geo-cache"],
    "routing-api": ["geo-svc", "eta-svc"],
    "invoicing-api": ["rates-db", "shipments-api"],
    "dispatch-svc": ["routing-api", "ops-db"],
    "eta-svc": ["geo-svc", "telemetry-store"],
    "geo-svc": ["geo-cache"],
    "id-svc": ["ops-db"],
}.items() for b in bs] + [(a, b, A) for a, b in [
    ("dispatch-svc", "event-bus"), ("tracking-api", "event-bus"), ("eta-svc", "event-bus"), ("invoicing-api", "event-bus"),
]]

TEAMS = {"Customer": "#customer-oncall", "Dispatch": "#dispatch-oncall", "Platform": "#platform-oncall"}
IST, CET, PST = "Asia/Kolkata", "Europe/Berlin", "America/Los_Angeles"
PEOPLE = [
    ("Ava Thompson", "ava", PST, "Customer", True), ("Rohan Gupta", "rohan", IST, "Customer", False),
    ("Lukas Meyer", "lukas", CET, "Dispatch", True), ("Tara Singh", "tara", IST, "Dispatch", False),
    ("Ben Carter", "ben", PST, "Dispatch", False), ("Mia Novak", "mia", CET, "Platform", True),
    ("Arjun Das", "arjun", IST, "Platform", False), ("Zoe Adams", "zoe", PST, "Platform", False),
]
FEATURES = {
    "Shipment Booking": ["shipments-api", "dispatch-svc", "id-svc"],
    "Live Tracking": ["tracking-api", "eta-svc"],
    "Driver Routing": ["routing-api", "geo-svc", "driver-bff"],
    "Invoicing": ["invoicing-api", "rates-db"],
}
CUSTOMER_NAMES = ["FreshCart", "Bolt Hardware", "Pine Furniture", "Sunrise Pharma", "Tidal Seafood",
                  "Corner Books", "Peak Electronics", "Greenleaf Organics", "Anvil Tools", "Mosaic Apparel"]
PATTERNS = [
    dict(key="geo_cache_evict", service="geo-cache", kind="config", occurrences=3, action="rollback",
         deploy="Lower geo-cache maxmemory eviction threshold",
         title="geo-cache eviction storm slows routing",
         summary="Config change lowered geo-cache memory limit; eviction storm made geo lookups slow and routing timed out. Fixed by rolling back the config.",
         fix="Roll back the geo-cache memory config", ttr=(6, 12)),
    dict(key="event_bus_lag", service="event-bus", kind="infra", occurrences=2, action="scale",
         deploy="Event bus broker node replacement",
         title="event-bus consumer lag after broker replacement",
         summary="Broker replacement on event-bus caused consumer lag on async dependents. Fixed by scaling consumers.",
         fix="Scale up consumers until lag drains", ttr=(12, 20)),
]
CONFIG = dict(name="globex", seed=2002, services=SERVICES, deps=DEPS, teams=TEAMS, people=PEOPLE,
              features=FEATURES, customers=CUSTOMER_NAMES, patterns=PATTERNS,
              generic_roots=["ops-db", "telemetry-store", "id-svc", "rates-db", "geo-svc"],
              runbooks=["geo-cache", "event-bus", "ops-db"], deploys_per_service_90d=14, n_generic_incidents=6)
