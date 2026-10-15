"""Indexes. Create them BEFORE loading data (the full-text index only sees nodes added after it exists)."""

RANGE_INDEXES = [
    ("Service", "name"),
    ("Deploy", "id"),
    ("Deploy", "ts"),
    ("Alert", "id"),
    ("Alert", "ts"),
    ("Incident", "id"),
    ("Incident", "started_at"),
    ("Person", "handle"),
    ("Team", "name"),
    ("Feature", "name"),
    ("Customer", "name"),
    ("Lesson", "pattern"),
    ("Hypothesis", "id"),
    ("Finding", "id"),
    ("Investigation", "id"),
]

FULLTEXT_INDEXES = [("Incident", "summary")]


def ensure_schema(graph) -> None:
    for label, prop in RANGE_INDEXES:
        try:
            graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except Exception as e:
            if "already indexed" not in str(e):
                raise
    for label, prop in FULLTEXT_INDEXES:
        try:
            graph.query("CALL db.idx.fulltext.createNodeIndex($label, $prop)", {"label": label, "prop": prop})
        except Exception as e:
            if "already" not in str(e).lower():
                raise
