from __future__ import annotations

import uuid
from pathlib import Path

from solux.modules.spec import ConfigField, ContextKey, Dependency, ModuleSpec
from solux.workflows.models import Context, Step


def handle(ctx: Context, step: Step) -> Context:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("output.vector_store requires chromadb. Install with: pip install chromadb") from exc

    collection_name = str(step.config.get("collection", "solux"))
    db_path = Path(str(step.config.get("db_path", "~/.local/share/solux/chroma"))).expanduser()
    embedding_key = str(step.config.get("embedding_key", "embedding"))
    text_key = str(step.config.get("text_key", "output_text"))
    id_key = str(step.config.get("id_key", ""))

    db_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name=collection_name)

    text = str(ctx.data.get(text_key, ""))
    embedding = ctx.data.get(embedding_key)

    if id_key and id_key in ctx.data:
        doc_id = str(ctx.data[id_key])
    else:
        doc_id = ctx.source_id or uuid.uuid4().hex

    add_kwargs: dict = {
        "ids": [doc_id],
        "documents": [text],
    }
    if embedding is not None and isinstance(embedding, list):
        add_kwargs["embeddings"] = [embedding]

    collection.upsert(**add_kwargs)

    ctx.data["vector_store_id"] = doc_id
    ctx.logger.info("vector_store: upserted doc id=%s to collection=%s", doc_id, collection_name)
    return ctx


MODULE = ModuleSpec(
    name="vector_store",
    version="0.1.0",
    category="output",
    description="Store text (and optional embedding) in a ChromaDB vector store.",
    handler=handle,
    aliases=("output.vector_store",),
    dependencies=(Dependency(name="chromadb", kind="binary", hint="pip install chromadb"),),
    config_schema=(
        ConfigField(name="collection", description="ChromaDB collection name", default="solux"),
        ConfigField(
            name="db_path", description="Path to ChromaDB storage directory", default="~/.local/share/solux/chroma"
        ),
        ConfigField(name="embedding_key", description="Context key for embedding vector", default="embedding"),
        ConfigField(name="text_key", description="Context key for document text", default="output_text"),
        ConfigField(name="id_key", description="Context key for document ID (default: ctx.source_id)", default=""),
    ),
    reads=(
        ContextKey("output_text", "Document text (configurable via text_key)"),
        ContextKey("embedding", "Embedding vector (configurable via embedding_key)"),
    ),
    writes=(ContextKey("vector_store_id", "ID of the upserted document"),),
    safety="trusted_only",
)
