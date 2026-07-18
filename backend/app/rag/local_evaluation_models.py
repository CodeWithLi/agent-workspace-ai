from __future__ import annotations

import asyncio
import math
import os
from typing import Any

from app.core.llm import LLMGatewayError
from app.rag.chunking import ChunkingConfig, SemanticStructuralChunker


EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
CHAT_MODEL_REPOSITORY = "bartowski/Qwen2.5-0.5B-Instruct-GGUF"
CHAT_MODEL_FILENAME = "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"
CHAT_MODEL_REVISION = "41ba88dbac95fed2528c92514c131d73eb5a174b"


class LocalOpenModelSuite:
    """Pinned CPU model suite used only by the reproducible RAG quality gate."""

    def __init__(self) -> None:
        self._embedding_model: Any | None = None
        self._reranker: Any | None = None
        self._llm: Any | None = None
        self._threads = max(1, min(os.cpu_count() or 1, 4))
        self._reranker_candidate_limit = 40

    @property
    def api_key(self) -> str:
        return "local-open-models"

    @property
    def base_url(self) -> str:
        return "local://open-models"

    @property
    def model(self) -> str:
        return f"{CHAT_MODEL_REPOSITORY}/{CHAT_MODEL_FILENAME}"

    @property
    def embedding_model_name(self) -> str:
        return EMBEDDING_MODEL

    @property
    def reranker_model_name(self) -> str:
        return RERANKER_MODEL

    @property
    def model_revisions(self) -> dict[str, dict[str, str]]:
        return {
            "embedding": {"model": EMBEDDING_MODEL, "revision": EMBEDDING_REVISION},
            "reranker": {"model": RERANKER_MODEL, "revision": RERANKER_REVISION},
            "chat_and_judge": {
                "model": CHAT_MODEL_REPOSITORY,
                "filename": CHAT_MODEL_FILENAME,
                "revision": CHAT_MODEL_REVISION,
            },
        }

    def _load_embedding_model(self) -> Any:
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer

            self._embedding_model = SentenceTransformer(
                EMBEDDING_MODEL,
                revision=EMBEDDING_REVISION,
                device="cpu",
                trust_remote_code=False,
            )
        return self._embedding_model

    def _load_reranker(self) -> Any:
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(
                RERANKER_MODEL,
                revision=RERANKER_REVISION,
                device="cpu",
                trust_remote_code=False,
                max_length=512,
            )
        return self._reranker

    def _load_llm(self) -> Any:
        if self._llm is None:
            from huggingface_hub import hf_hub_download
            from llama_cpp import Llama

            model_path = hf_hub_download(
                repo_id=CHAT_MODEL_REPOSITORY,
                filename=CHAT_MODEL_FILENAME,
                revision=CHAT_MODEL_REVISION,
            )
            self._llm = Llama(
                model_path=model_path,
                n_ctx=4096,
                n_batch=256,
                n_threads=self._threads,
                seed=42,
                verbose=False,
            )
        return self._llm

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        model = self._load_embedding_model()
        vectors = model.encode(
            [f"{prefix}: {text}" for text in texts],
            batch_size=16,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [list(map(float, vector)) for vector in vectors]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self._encode, texts, "passage")
        except Exception as exc:
            raise LLMGatewayError(f"Local embedding model failed: {type(exc).__name__}: {exc}") from exc

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return await asyncio.to_thread(self._encode, texts, "query")
        except Exception as exc:
            raise LLMGatewayError(f"Local query embedding model failed: {type(exc).__name__}: {exc}") from exc

    def build_semantic_chunker(
        self,
        config: ChunkingConfig,
        threshold: float,
    ) -> SemanticStructuralChunker:
        from chonkie import SemanticChunker, SentenceTransformerEmbeddings

        embeddings = SentenceTransformerEmbeddings(model=self._load_embedding_model())
        semantic_chunker = SemanticChunker(
            embedding_model=embeddings,
            threshold=threshold,
            chunk_size=config.child_tokens,
            similarity_window=3,
            min_sentences_per_chunk=1,
            min_characters_per_sentence=12,
            delim=["\u3002", "\uff01", "\uff1f", ". ", "! ", "? ", "\n"],
            include_delim="prev",
        )
        return SemanticStructuralChunker(semantic_chunker, config)

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            factor = math.exp(-value)
            return 1.0 / (1.0 + factor)
        factor = math.exp(value)
        return factor / (1.0 + factor)

    def _rerank(self, query: str, rows: list[dict]) -> list[dict]:
        model = self._load_reranker()
        candidates = rows[: self._reranker_candidate_limit]
        raw_scores = model.predict(
            [(query, row["content"]) for row in candidates],
            batch_size=8,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        if hasattr(raw_scores, "tolist"):
            raw_scores = raw_scores.tolist()
        scores: list[float] = []
        for raw_score in raw_scores:
            if isinstance(raw_score, list):
                raw_score = raw_score[0]
            scores.append(self._sigmoid(float(raw_score)))
        for row, score in zip(candidates, scores):
            row["rerank_score"] = round(score, 4)
            row["score"] = round(0.35 * row["score"] + 0.65 * score, 4)
            row["rerank_fallback"] = False
        return sorted(candidates, key=lambda row: row["score"], reverse=True) + rows[len(candidates) :]

    async def rerank(self, query: str, rows: list[dict]) -> list[dict]:
        if not rows:
            return rows
        try:
            return await asyncio.to_thread(self._rerank, query, rows)
        except Exception as exc:
            raise LLMGatewayError(f"Local reranker failed: {type(exc).__name__}: {exc}") from exc

    async def healthcheck(self) -> None:
        rows = await self.rerank("Connection test", [{"content": "Connection test", "score": 1.0}])
        if not rows or rows[0].get("rerank_fallback") is not False:
            raise RuntimeError("Local reranker healthcheck failed")

    @staticmethod
    def _judge_response_format() -> dict[str, Any]:
        return {
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "faithfulness": {"type": "number", "minimum": 0, "maximum": 1},
                    "answer_relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "citation_correctness": {"type": "number", "minimum": 0, "maximum": 1},
                    "refusal_correct": {"type": "boolean"},
                    "reason": {"type": "string", "minLength": 1},
                },
                "required": [
                    "faithfulness",
                    "answer_relevance",
                    "citation_correctness",
                    "refusal_correct",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _query_response_format() -> dict[str, Any]:
        return {
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 3,
                    }
                },
                "required": ["queries"],
                "additionalProperties": False,
            },
        }

    def _chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, str] | None,
    ) -> str:
        effective_format: dict[str, Any] | None = response_format
        max_tokens = 320
        if "strict RAG evaluation judge" in system_prompt:
            effective_format = self._judge_response_format()
            max_tokens = 256
        elif '"queries"' in system_prompt:
            effective_format = self._query_response_format()
            max_tokens = 160
        request: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "max_tokens": max_tokens,
        }
        if effective_format:
            request["response_format"] = effective_format
        result = self._load_llm().create_chat_completion(**request)
        content = result["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Local chat model returned no content")
        return content.strip()

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        del model
        try:
            return await asyncio.to_thread(self._chat, system_prompt, user_prompt, response_format)
        except Exception as exc:
            raise LLMGatewayError(f"Local chat model failed: {type(exc).__name__}: {exc}") from exc
