"""Gemini embeddings.

gemini-embedding-2 has no task_type parameter; retrieval is signalled with text
prefixes instead (Gemini embeddings guide). Each input is wrapped in its own
Content object, because a plain list of parts is aggregated into ONE embedding.
"""

from google import genai
from google.genai import types

from .config import Config
from .retry import with_retry

BATCH_SIZE = 50


def document_text(record: dict) -> str:
    return f"title: {record['title']} | text: {record['text']}"


def query_text(question: str) -> str:
    return f"task: search result | query: {question}"


class Embedder:
    def __init__(self, cfg: Config, client: genai.Client):
        self.cfg = cfg
        self.client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        contents = [types.Content(parts=[types.Part(text=t)]) for t in batch]
        result = with_retry(
            lambda: self.client.models.embed_content(
                model=self.cfg.embedding_model,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=self.cfg.embedding_dim),
            )
        )
        embeddings = result.embeddings or []
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"Expected {len(batch)} embeddings, got {len(embeddings)}; "
                "inputs may have been aggregated"
            )
        return [e.values for e in embeddings]

    def embed_query(self, question: str) -> list[float]:
        return self.embed([query_text(question)])[0]
