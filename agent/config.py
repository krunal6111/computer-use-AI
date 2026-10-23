import os

from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash-lite",
    "nim": "nvidia/nemotron-3.5-super-vl-120b-a12b",
}
# Tried in order when the current Gemini model is overloaded (503) or times out.
GEMINI_FALLBACKS = ["gemini-3.5-flash", "gemini-3.8-flash"]
# Less thinking = faster answers. flash-lite and flash at "minimal" still
# clicked accurately in testing (5s vs 11s at the default); 3.8-flash
# rejects "minimal", so it keeps the "low" default below.
GEMINI_THINKING = {"gemini-3.5-flash-lite": "minimal", "gemini-3.5-flash": "minimal"}
GEMINI_DEFAULT_THINKING = "low"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SCREENSHOT_WIDTH = 1280  # width sent to the model (JPEG): ~100KB vs ~320KB PNG at 1440
KEEP_SCREENSHOTS = 2     # older screenshots are dropped from history to save tokens
SETTLE_SECONDS = 0.5     # wait after an action so the UI can update...
SLOW_SETTLE_SECONDS = 2.0  # ...longer after actions that load a page or app
REQUEST_TIMEOUT = 90     # seconds per model call
# The free NIM endpoint queues requests under load; 30s cut off answers that arrived later.
NIM_REQUEST_TIMEOUT = 60
LOG_DIR = os.path.join(_REPO_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
NIM_LATENCY_LOG = os.path.join(LOG_DIR, "latency.log")
ERROR_LOG = os.path.join(LOG_DIR, "errors.log")
MAX_RETRIES = 8
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
