import sys
from types import SimpleNamespace

import pytest

from app.rag.vector_store import MilvusVectorStore, VectorStoreError


class FakeFieldSchema:
    def __init__(self, name, dtype, **kwargs):
        self.name = name
        self.dtype = dtype
        self.options = kwargs


class FakeCollectionSchema:
    def __init__(self, fields, description=""):
        self.fields = fields
        self.description = description
        self.functions = []

    def add_function(self, function):
        self.functions.append(function)


class FakeFunction:
    def __init__(self, **kwargs):
        self.options = kwargs


class FakeHit:
    def __init__(self):
        self.id = "vector-1"
        self.score = 0.8
        self.entity = {"document_id": 1, "project_id": 2, "index_version": 3, "content": "content"}


class FakeCollection:
    instances = {}

    def __new__(cls, name, schema=None):
        if name in cls.instances:
            return cls.instances[name]
        instance = super().__new__(cls)
        cls.instances[name] = instance
        return instance

    def __init__(self, name, schema=None):
        if getattr(self, "initialized", False):
            return
        self.initialized = True
        self.name = name
        self.schema = schema
        self.indexes = []
        self.upserts = []
        self.hybrid_calls = []

    def create_index(self, field_name, index_params):
        self.indexes.append((field_name, index_params))

    def load(self):
        return None

    def flush(self):
        return None

    def upsert(self, data):
        self.upserts.append(data)

    def hybrid_search(self, **kwargs):
        self.hybrid_calls.append(kwargs)
        return [[FakeHit()]]


class FakeAnnSearchRequest:
    def __init__(self, **kwargs):
        self.options = kwargs


def test_milvus_v4_schema_and_multi_vector_hybrid_protocol(monkeypatch) -> None:
    FakeCollection.instances.clear()
    fake_module = SimpleNamespace(
        Collection=FakeCollection,
        CollectionSchema=FakeCollectionSchema,
        DataType=SimpleNamespace(
            VARCHAR="varchar",
            INT64="int64",
            SPARSE_FLOAT_VECTOR="sparse",
            FLOAT_VECTOR="float",
        ),
        FieldSchema=FakeFieldSchema,
        Function=FakeFunction,
        FunctionType=SimpleNamespace(BM25="bm25"),
        connections=SimpleNamespace(connect=lambda **_kwargs: None),
        utility=SimpleNamespace(has_collection=lambda _name: False),
        AnnSearchRequest=FakeAnnSearchRequest,
        RRFRanker=lambda value: ("rrf", value),
    )
    monkeypatch.setitem(sys.modules, "pymilvus", fake_module)
    store = MilvusVectorStore()
    monkeypatch.setattr("app.rag.vector_store.settings.rag_multi_vector_enabled", True)

    assert store.connect() is True
    collection = next(iter(FakeCollection.instances.values()))
    assert store.supports_hybrid is True
    assert store.supports_multi_vector is True
    assert {field.name for field in collection.schema.fields} >= {
        "content",
        "sparse",
        "embedding",
        "parent_embedding",
        "index_version",
        "owner_id",
    }
    assert collection.schema.functions[0].options["function_type"] == "bm25"
    assert {field for field, _params in collection.indexes} == {"embedding", "parent_embedding", "sparse"}

    store.upsert(
        "vector-1",
        1,
        2,
        "content",
        [0.1, 0.2],
        index_version=3,
        parent_embedding=[0.3, 0.4],
        owner_id=7,
    )
    assert collection.upserts[0][0]["index_version"] == 3
    assert collection.upserts[0][0]["parent_embedding"] == [0.3, 0.4]
    assert collection.upserts[0][0]["owner_id"] == 7
    rows = store.hybrid_search("query", [0.1, 0.2], project_id=2, limit=5)
    assert [request.options["anns_field"] for request in collection.hybrid_calls[0]["reqs"]] == [
        "sparse",
        "embedding",
        "parent_embedding",
    ]
    assert rows == [
        {
            "vector_id": "vector-1",
            "document_id": 1,
            "index_version": 3,
            "content": "content",
            "score": 0.8,
        }
    ]
    store.hybrid_search(
        "query",
        [0.1, 0.2],
        project_id=None,
        limit=5,
        owner_id=7,
        document_ids=[9, 4, 9],
    )
    assert {
        request.options["expr"] for request in collection.hybrid_calls[1]["reqs"]
    } == {"project_id == 0 and owner_id == 7 and document_id in [4, 9]"}


def test_milvus_failure_is_not_silenced_when_fallback_is_disabled(monkeypatch) -> None:
    fake_module = SimpleNamespace(
        connections=SimpleNamespace(connect=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))),
    )
    monkeypatch.setitem(sys.modules, "pymilvus", fake_module)
    monkeypatch.setattr("app.rag.vector_store.settings.vector_fallback_enabled", False)

    with pytest.raises(VectorStoreError, match="connection failed"):
        MilvusVectorStore().connect()


def test_legacy_collection_never_searches_all_personal_vectors(monkeypatch) -> None:
    store = MilvusVectorStore()
    store.supports_owner_filter = False
    monkeypatch.setattr("app.rag.vector_store.settings.vector_fallback_enabled", True)

    assert store._scope_expression(None, owner_id=7) is None

    monkeypatch.setattr("app.rag.vector_store.settings.vector_fallback_enabled", False)
    with pytest.raises(VectorStoreError, match="owner isolation"):
        store._scope_expression(None, owner_id=7)
