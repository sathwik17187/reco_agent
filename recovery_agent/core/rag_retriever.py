"""
rag_retriever.py — Layer 3a: ChromaDB vector store backed by Ollama embeddings.

Indexes the policy document chunks from data/policy_docs/*.txt using the
nomic-embed-text model (via Ollama) and exposes a retrieve() method that
returns the top-k most relevant policy snippets for a given query.

The index is built once at startup and persisted to chroma_db/ so subsequent
runs don't re-embed. Call build_index() on first run or when policy docs change.

Usage:
    retriever = RAGRetriever(persist_dir="chroma_db")
    retriever.build_index("data/policy_docs/")
    snippets = retriever.retrieve("do_not_honor enterprise large amount", top_k=3)
"""

import os
import glob
import hashlib
import json
from typing import List

import chromadb
import ollama


EMBED_MODEL      = "nomic-embed-text"
COLLECTION_NAME  = "recovery_policies"
MANIFEST_FILE    = "chroma_db/.index_manifest.json"


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

_embed_client = None
_embed_cache: dict = {}

def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        _embed_client = ollama.Client(timeout=10.0)
    return _embed_client

def _embed(text: str) -> List[float]:
    """Call Ollama nomic-embed-text and return the embedding vector with in-memory caching."""
    if text in _embed_cache:
        return _embed_cache[text]
    try:
        client = _get_embed_client()
        response = client.embeddings(model=EMBED_MODEL, prompt=text)
        emb = response["embedding"]
        _embed_cache[text] = emb
        return emb
    except Exception:
        return [0.0] * 768


def _file_hash(path: str) -> str:
    """MD5 of file content — used to detect doc changes."""
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# ---------------------------------------------------------------------------
# RAGRetriever
# ---------------------------------------------------------------------------

class RAGRetriever:
    """
    ChromaDB-backed retriever for payment recovery policy documents.

    Attributes:
        persist_dir  : directory where ChromaDB persists its SQLite store
        collection   : ChromaDB collection (loaded after build_index or load_index)
    """

    def __init__(self, persist_dir: str = "chroma_db"):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        self.manifest_file = os.path.join(persist_dir, ".index_manifest.json")
        self._client: chromadb.ClientAPI = chromadb.PersistentClient(path=persist_dir)
        self.collection = None

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def build_index(self, policy_docs_dir: str, force: bool = False) -> int:
        """
        Embed all .txt files in policy_docs_dir and upsert into ChromaDB.

        Skips files whose content hasn't changed since the last run
        (detected via MD5 manifest) unless force=True.

        Returns the number of documents upserted.
        """
        txt_files = sorted(glob.glob(os.path.join(policy_docs_dir, "*.txt")))
        if not txt_files:
            raise FileNotFoundError(
                f"No .txt policy files found in '{policy_docs_dir}'. "
                "Run data/policy_docs/playbook_gen.py first."
            )

        # Load manifest (doc_id → last_hash)
        manifest: dict = {}
        if os.path.exists(self.manifest_file) and not force:
            with open(self.manifest_file, "r") as f:
                manifest = json.load(f)

        self.collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        upserted = 0
        skipped  = 0

        for filepath in txt_files:
            doc_id   = os.path.splitext(os.path.basename(filepath))[0]  # e.g. "card_expired"
            content  = open(filepath, encoding="utf-8").read().strip()
            cur_hash = _file_hash(filepath)

            # Skip if unchanged
            if manifest.get(doc_id) == cur_hash and not force:
                skipped += 1
                continue

            embedding = _embed(content)
            self.collection.upsert(
                ids=[doc_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[{"filename": os.path.basename(filepath), "doc_id": doc_id}],
            )
            manifest[doc_id] = cur_hash
            upserted += 1
            print(f"  [RAG] indexed: {doc_id}")

        # Save manifest
        with open(self.manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        total = self.collection.count()
        print(f"[RAG] Index ready: {total} docs total ({upserted} upserted, {skipped} unchanged)")
        return upserted

    # ------------------------------------------------------------------
    # Loading existing index (no re-embed)
    # ------------------------------------------------------------------

    def load_index(self) -> bool:
        """
        Load an existing ChromaDB collection without re-embedding.
        Returns True if collection exists and has documents, False otherwise.
        """
        try:
            self.collection = self._client.get_collection(name=COLLECTION_NAME)
            count = self.collection.count()
            if count == 0:
                return False
            print(f"[RAG] Loaded existing index: {count} policy documents")
            return True
        except Exception:
            return False

    def ensure_index(self, policy_docs_dir: str) -> None:
        """
        Load existing index if available; build it if not.
        Typical usage in the orchestrator — call this once at startup.
        """
        if not self.load_index():
            print("[RAG] No existing index found — building now...")
            self.build_index(policy_docs_dir)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """
        Embed query and return the top_k most relevant policy document texts.

        Args:
            query  : natural-language query string (built from event context)
            top_k  : number of snippets to return (default 3)

        Returns:
            List of policy document strings, most relevant first.
        """
        if self.collection is None:
            raise RuntimeError(
                "RAGRetriever has no index loaded. "
                "Call build_index() or ensure_index() first."
            )

        query_embedding = _embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        docs      = results["documents"][0]      # list of strings
        metadatas = results["metadatas"][0]      # list of dicts
        distances = results["distances"][0]      # cosine distances (lower = more similar)

        # Attach source name to each snippet for audit trail
        annotated = []
        for doc, meta, dist in zip(docs, metadatas, distances):
            source = meta.get("doc_id", "unknown")
            similarity = round(1 - dist, 4)     # convert cosine distance → similarity
            annotated.append(f"[Policy: {source} | similarity={similarity}]\n{doc}")

        return annotated

    def retrieve_raw(self, query: str, top_k: int = 3) -> List[dict]:
        """
        Same as retrieve() but returns structured dicts with doc_id, text, similarity.
        Used by the audit log to record which policies influenced a diagnosis.
        """
        if self.collection is None:
            raise RuntimeError("Index not loaded.")

        query_embedding = _embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "doc_id":     meta.get("doc_id", "unknown"),
                "similarity": round(1 - dist, 4),
                "text":       doc,
            })
        return output


# ---------------------------------------------------------------------------
# Query builder helper (used by orchestrator / diagnoser)
# ---------------------------------------------------------------------------

def build_query(event: dict, detection_category: str) -> str:
    """
    Build a retrieval query string from event context + detection category.
    Richer context → better retrieval.

    Examples:
      "do_not_honor enterprise amount 72774"
      "likely_uncollectable smb invoice 90 days overdue contact_attempts 5"
    """
    parts = [detection_category.lower().replace("_", " ")]

    etype = event.get("event_type", "")
    parts.append(event.get("customer_segment", ""))

    if etype == "failed_payment":
        code = event.get("failure_code", "")
        method = event.get("payment_method", "")
        parts += [code, method, f"amount {int(event.get('amount', 0))}"]
        if event.get("retry_count", 0) > 1:
            parts.append(f"retry_count {event['retry_count']}")

    elif etype == "abandoned_checkout":
        parts += [
            f"abandoned {event.get('abandoned_at_step', '')} step",
            f"cart value {int(event.get('cart_value', 0))}",
        ]

    elif etype == "overdue_invoice":
        parts += [
            f"invoice {event.get('days_overdue', 0)} days overdue",
            f"status {event.get('invoice_status', '')}",
            f"contact attempts {event.get('contact_attempts', 0)}",
            f"amount {int(event.get('amount', 0))}",
        ]

    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    policy_dir = sys.argv[1] if len(sys.argv) > 1 else "data/policy_docs"

    retriever = RAGRetriever(persist_dir="chroma_db")
    retriever.build_index(policy_dir, force=False)

    test_queries = [
        ("do_not_honor enterprise large amount card",          "SOFT_DECLINE"),
        ("insufficient_funds retail retry payment",             "INSUFFICIENT_FUNDS"),
        ("invoice 95 days overdue smb contact attempts 5",     "LIKELY_UNCOLLECTABLE"),
        ("abandoned confirm step high intent cart recovery",    "HIGH_INTENT_ABANDON"),
        ("card expired update link retry",                      "CARD_EXPIRED"),
    ]

    print("\n=== Retrieval Tests ===")
    for query, label in test_queries:
        print(f"\nQuery [{label}]: {query}")
        snippets = retriever.retrieve(query, top_k=2)
        for i, s in enumerate(snippets, 1):
            header = s.split("\n")[0]
            print(f"  [{i}] {header}")
