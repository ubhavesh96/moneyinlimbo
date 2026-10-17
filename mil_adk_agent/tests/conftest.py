import os
import tempfile

# Force offline demo mode and an isolated runtime folder BEFORE mil is imported.
os.environ["MIL_SKIP_DOTENV"] = "1"  # never read the real .env
os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ["MIL_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="mil_test_")
os.environ["MIL_NO_SEED"] = "1"  # tests create the cases they need
