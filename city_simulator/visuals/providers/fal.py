"""fal.ai-backed Provider: submits to fal's queue REST API, polls until
done, downloads results locally via storage.py. See fal's docs at
https://fal.ai/docs/model-apis/model-endpoints/queue for the underlying
submit/status/result endpoints this wraps.
"""

import base64
import mimetypes
import time

import requests

from .. import config
from .. import storage
from .base import Provider

_QUEUE_BASE = "https://queue.fal.run"


def _check_response(resp: requests.Response):
    """requests' default raise_for_status() message is just the status
    line -- fal.ai's actual explanation (bad key, no model access, no
    credits, ...) is in the response body, which this surfaces instead of
    hiding."""
    if not resp.ok:
        raise requests.exceptions.HTTPError(
            f"fal.ai returned {resp.status_code} {resp.reason} for {resp.url}: {resp.text}",
            response=resp,
        )


def _require_api_key() -> str:
    if not config.FAL_API_KEY:
        raise RuntimeError(
            "FAL_KEY environment variable is not set -- get a key from "
            "fal.ai and `export FAL_KEY=...` before generating images/video."
        )
    return config.FAL_API_KEY


def _to_data_uri(path: str, default_mime: str = "application/octet-stream") -> str:
    mime = mimetypes.guess_type(path)[0] or default_mime
    data = base64.b64encode(open(path, "rb").read()).decode("ascii")
    return f"data:{mime};base64,{data}"


class FalProvider(Provider):
    def __init__(self):
        self._session = requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Key {_require_api_key()}", "Content-Type": "application/json"}

    def _submit_and_wait(self, model_id: str, input_payload: dict) -> dict:
        submit = self._session.post(
            f"{_QUEUE_BASE}/{model_id}", json=input_payload, headers=self._headers(), timeout=60,
        )
        _check_response(submit)
        submit_data = submit.json()
        request_id = submit_data["request_id"]

        # Prefer the URLs fal hands back over hand-building them: for a
        # model id with extra path segments (e.g.
        # "google/gemini-omni-flash/v1.1/image-to-video"), status/result
        # don't just live at "{model_id}/requests/{id}/..." -- fal's own
        # status_url/response_url are the ones that actually work.
        status_url = submit_data.get("status_url") or f"{_QUEUE_BASE}/{model_id}/requests/{request_id}/status"
        result_url = submit_data.get("response_url") or f"{_QUEUE_BASE}/{model_id}/requests/{request_id}"

        deadline = time.monotonic() + config.FAL_TIMEOUT_SECONDS
        while True:
            status_resp = self._session.get(status_url, headers=self._headers(), timeout=30)
            _check_response(status_resp)
            status = status_resp.json().get("status")
            if status == "COMPLETED":
                break
            if status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"fal.ai request {request_id} {status.lower()}: {status_resp.text}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"fal.ai request {request_id} did not complete within {config.FAL_TIMEOUT_SECONDS}s")
            time.sleep(config.FAL_POLL_INTERVAL_SECONDS)

        result_resp = self._session.get(result_url, headers=self._headers(), timeout=30)
        _check_response(result_resp)
        return result_resp.json()

    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        model_id = config.FAL_IMAGE_EDIT_MODEL if image_paths else config.FAL_TEXT_TO_IMAGE_MODEL
        payload = {"prompt": prompt, **config.IMAGE_DEFAULTS, **options}
        if image_paths:
            payload["image_urls"] = [_to_data_uri(p, default_mime="image/png") for p in image_paths]

        result = self._submit_and_wait(model_id, payload)

        images = []
        for image in result.get("images", []):
            local_path = storage.save_url(image["url"])
            images.append({
                "local_path": str(local_path), "url": storage.relative_path(local_path),
                "width": image.get("width"), "height": image.get("height"),
                "content_type": image.get("content_type"),
            })
        return {"images": images, "description": result.get("description", "")}

    def generate_video(self, prompt: str, image_path: str, **options) -> dict:
        payload = {
            "prompt": prompt, "image_url": _to_data_uri(image_path, default_mime="image/png"),
            **config.VIDEO_DEFAULTS, **options,
        }
        result = self._submit_and_wait(config.FAL_IMAGE_TO_VIDEO_MODEL, payload)
        return {"video": self._save_video(result["video"])}

    def generate_video_from_reference(self, prompt: str, video_path: str = None,
                                       image_paths: list = None, **options) -> dict:
        payload = {"prompt": prompt, **config.VIDEO_REFERENCE_DEFAULTS, **options}
        if image_paths:
            payload["image_urls"] = [_to_data_uri(p, default_mime="image/png") for p in image_paths]
        if video_path:
            # fal caps each reference video at 3 seconds -- see
            # config.yaml's comment on reference_to_video_model.
            payload["reference_video_urls"] = [_to_data_uri(video_path, default_mime="video/mp4")]

        result = self._submit_and_wait(config.FAL_REFERENCE_TO_VIDEO_MODEL, payload)
        return {"video": self._save_video(result["video"])}

    def _save_video(self, video: dict) -> dict:
        local_path = storage.save_url(video["url"])
        return {
            "local_path": str(local_path), "url": storage.relative_path(local_path),
            "content_type": video.get("content_type"), "file_size": video.get("file_size"),
        }
