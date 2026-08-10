"""
Conversation memory.

`ChatLog` is the plain append-only transcript every board keeps. `RagMemory`
adds a ChromaDB index over the workspace directory; it is only instantiated when
FEATURE_RAG is on, so boards without the headroom never import chromadb or
sentence-transformers.
"""
import hashlib
import os
import time

from . import config


class ChatLog:
    """Append-only markdown transcript at $BASE_DIR/workspace/history.md."""

    def __init__(self, path):
        self.path = path
        self.workspace_dir = os.path.dirname(path)

    def save(self, user_text, assistant_text):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"U: {user_text}\nA: {assistant_text}\n---\n")

    def get_recent_turns(self, n=1):
        """Return the last n turns as raw '---'-separated blocks."""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read()
            turns = [t.strip() for t in content.split("---") if t.strip()]
            return turns[-n:]
        except Exception:
            return []

    def query_knowledge(self, prompt):
        """Without RAG there is no knowledge base to consult."""
        return ""

    def start_workers(self):
        """No background work in the plain log."""
        return []


class RagMemory(ChatLog):
    """ChatLog plus a vector index of the workspace directory."""

    def __init__(self, path):
        super().__init__(path)

        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions

        self.chroma_client = chromadb.PersistentClient(
            path=os.path.join(self.workspace_dir, ".chroma_db"),
            settings=Settings(anonymized_telemetry=False),
        )
        self.emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL, device="cpu"
        )
        self.knowledge_col = self.chroma_client.get_or_create_collection(
            "knowledge", embedding_function=self.emb_fn
        )
        self.file_registry = {}

    def sync_workspace(self):
        """Daemon loop: re-index workspace files whose mtime moved."""
        while True:
            try:
                for filename in os.listdir(self.workspace_dir):
                    if filename.startswith(".") or filename == "history.md":
                        continue
                    file_path = os.path.join(self.workspace_dir, filename)
                    if not os.path.isfile(file_path):
                        continue

                    mtime = os.path.getmtime(file_path)
                    if file_path not in self.file_registry or mtime > self.file_registry[file_path]:
                        self._index_file(file_path)
                        self.file_registry[file_path] = mtime
            except Exception as e:
                print(f"Sync Error: {e}")
            time.sleep(5)

    def _index_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 10]
            for i, chunk in enumerate(chunks):
                chunk_id = f"{hashlib.md5(file_path.encode()).hexdigest()}_{i}"
                self.knowledge_col.upsert(
                    documents=[chunk], ids=[chunk_id], metadatas=[{"source": file_path}]
                )
        except Exception:
            pass

    def query_knowledge(self, prompt):
        """Nearest workspace chunks, or "" when nothing clears DIST_THRESHOLD."""
        try:
            k_results = self.knowledge_col.query(query_texts=[prompt], n_results=2)
            if k_results["documents"] and k_results["distances"][0][0] < config.DIST_THRESHOLD:
                return " | ".join(k_results["documents"][0])
        except Exception:
            pass
        return ""

    def start_workers(self):
        return [self.sync_workspace]


_memory = None


def get_memory():
    """Return the process-wide memory, built to match the board's feature flags."""
    global _memory
    if _memory is None:
        cls = RagMemory if config.FEATURE_RAG else ChatLog
        _memory = cls(config.HISTORY_FILE)
    return _memory
