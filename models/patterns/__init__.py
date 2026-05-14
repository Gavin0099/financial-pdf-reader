from mongoengine import (
    Document,
    EmbeddedDocument,
    StringField,
    ListField,
    EmbeddedDocumentField,
    IntField,
    BooleanField,
    DateTimeField,
)
from datetime import datetime, timezone


class PatternRunResult(EmbeddedDocument):
    """Result for a single pattern evaluation."""
    pattern_id = StringField(required=True)
    name_zh = StringField(required=True)
    status = StringField(
        choices=["triggered", "not_triggered", "insufficient_evidence"],
        default="not_triggered",
    )
    generated_observation = StringField(default="")
    source_claim_ids = ListField(StringField())
    missing_evidence_keys = ListField(StringField())
    requires_review = BooleanField(default=False)


class PatternRunReport(Document):
    """Persisted results of one run_pattern_analysis() call."""
    run_id = StringField(required=True, unique=True)
    document_id = StringField(required=True)
    stock_id = StringField(required=True)
    period = StringField(required=True)
    results = ListField(EmbeddedDocumentField(PatternRunResult))
    triggered_count = IntField(default=0)
    not_triggered_count = IntField(default=0)
    insufficient_count = IntField(default=0)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "pattern_run_reports",
        "indexes": ["document_id", "stock_id"],
    }
