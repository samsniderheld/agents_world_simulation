"""Central configuration for the Visuals tab -- provider selection, model
ids, and generation defaults live in config.yaml; the API key never does
(it's a secret, read from the FAL_KEY environment variable instead so it
never ends up committed to git). FAL_KEY can be exported normally or set
in a .env file at the project root (city_simulator/.env, see .env.example)
-- load_dotenv() below picks either up, and never overrides a real
environment variable that's already set.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).parent
_PROJECT_ROOT = _PACKAGE_DIR.parent
_YAML_PATH = _PACKAGE_DIR / "data" / "config.yaml"

load_dotenv(_PROJECT_ROOT / ".env")

with open(_YAML_PATH) as _f:
    _RAW = yaml.safe_load(_f)

PROVIDER = _RAW["provider"]

FAL_API_KEY = os.environ.get("FAL_KEY")
FAL_TEXT_TO_IMAGE_MODEL = _RAW["fal"]["text_to_image_model"]
FAL_IMAGE_EDIT_MODEL = _RAW["fal"]["image_edit_model"]
FAL_IMAGE_TO_VIDEO_MODEL = _RAW["fal"]["image_to_video_model"]
FAL_POLL_INTERVAL_SECONDS = _RAW["fal"]["poll_interval_seconds"]
FAL_TIMEOUT_SECONDS = _RAW["fal"]["timeout_seconds"]

IMAGE_DEFAULTS = _RAW["image_defaults"]
VIDEO_DEFAULTS = _RAW["video_defaults"]

UPLOADS_DIR = _PACKAGE_DIR / "data" / "uploads"
OUTPUTS_DIR = _PACKAGE_DIR / "data" / "outputs"
