"""
Shared pytest fixtures — mock mongoengine so pure-Python unit tests
can import service/model modules without a live MongoDB connection.
"""
import sys
import types


def _make_mongoengine_stub():
    """Return a minimal mongoengine stub that satisfies model imports."""
    me = types.ModuleType("mongoengine")

    class _Field:
        def __init__(self, *a, **kw):
            pass

    class _BaseDoc:
        meta = {}
        objects = None
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
        def save(self):
            pass

    for name in (
        "Document", "EmbeddedDocument",
        "StringField", "IntField", "FloatField", "BooleanField",
        "DateTimeField", "ListField", "DictField",
        "EmbeddedDocumentField", "ReferenceField",
    ):
        cls = _BaseDoc if name in ("Document", "EmbeddedDocument") else _Field
        setattr(me, name, cls)

    me.connect = lambda *a, **kw: None
    return me


# Install stubs before any test module imports them
if "mongoengine" not in sys.modules:
    sys.modules["mongoengine"] = _make_mongoengine_stub()

# Also stub out database connection module so service imports don't fail
_db_mod = types.ModuleType("database")
_db_client = types.ModuleType("database.mongo")
_db_client_mod = types.ModuleType("database.mongo.client")
_db_client_mod.connect_mongodb = lambda: None
sys.modules.setdefault("database", _db_mod)
sys.modules.setdefault("database.mongo", _db_client)
sys.modules.setdefault("database.mongo.client", _db_client_mod)
