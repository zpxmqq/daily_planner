import datetime
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOALS_FILE = os.path.join(BASE_DIR, "goals.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
PROFILE_FILE = os.path.join(BASE_DIR, "profile.json")
DB_FILE = os.path.join(BASE_DIR, "planner.db")

TODAY = str(datetime.date.today())
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

PRIO_LABEL = {"high": "高", "medium": "中", "low": "低"}
STATUS_EMOJI = {"顺利": "😊", "一般": "😐", "很累": "😴"}

MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com")

EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "").strip()
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", BASE_URL).strip()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
LOCAL_EMBEDDING_FALLBACK = os.getenv("LOCAL_EMBEDDING_FALLBACK", "1").strip() != "0"

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
RAG_MAX_CANDIDATES = int(os.getenv("RAG_MAX_CANDIDATES", "80"))
