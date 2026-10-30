import os

# Configure HuggingFace mirror for China (must be set before importing sentence-transformers)
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "researchflow.db")

SEEKDB_MODE = os.environ.get("SEEKDB_MODE", "auto")
# auto: try embedded (Linux) or remote (Windows), fallback to simulated
# embedded: force pyseekdb embedded mode (Linux only)
# remote: force pyseekdb remote server mode (host:port)
# simulated: force simulated mode (for demo without seekdb)

EMBEDDING_DIMENSION = 384
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = True

COLLECTION_NAME = "research_papers"
FULLTEXT_ANALYZER = "ik"

os.makedirs(DATA_DIR, exist_ok=True)
