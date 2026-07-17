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

    def create_index(self, field_name, index_params):
        self.indexes.append((field_name, index_params))

    def load(self):
        return None

    def flush(self):
        return None

    def upsert(self, data):
        self.upserts.append(data)

    def hybrid_search(self, **_kwargs):
        return [[FakeHit()]]


class FakeAnnSearchRequest:
    def __init__(self, **kwargs):
        self.options = kwargs


def test_milvus_v3_schema_and_hybrid_protocol(monkeypatch) -> None:
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

    assert store.connect() is True
    collection = next(iter(FakeCollection.instances.values()))
    assert store.supports_hybrid is True
    assert {field.name for field in collection.schema.fields} >= {"content", "sparse", "embedding", "index_version"}
    assert collection.schema.functions[0].options["function_type"] == "bm25"
    assert {field for field, _params in collection.indexes} == {"embedding", "sparse"}

    store.upsert("vector-1", 1, 2, "content", [0.1, 0.2], index_version=3)
    assert collection.upserts[0][0]["index_version"] == 3
    rows = store.hybrid_search("query", [0.1, 0.2], project_id=2, limit=5)
    assert rows == [
        {
            "vector_id": "vector-1",
            "document_id": 1,
            "index_version": 3,
            "content": "content",
            "score": 0.8,
        }
    ]


def test_milvus_failure_is_not_silenced_when_fallback_is_disabled(monkeypatch) -> None:
    fake_module = SimpleNamespace(
        connections=SimpleNamespace(connect=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))),
    )
    monkeypatch.setitem(sys.modules, "pymilvus", fake_module)
    monkeypatch.setattr("app.rag.vector_store.settings.vector_fallback_enabled", False)

    with pytest.raises(VectorStoreError, match="connection failed"):
        MilvusVectorStore().connect()
