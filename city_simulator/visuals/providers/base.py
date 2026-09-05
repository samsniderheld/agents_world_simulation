"""The provider interface every Visuals backend implements. `fal.py` is the
only implementation today; a local model server (ComfyUI, A1111, whatever)
is a `local.py` implementing the same two methods -- see
visuals/providers/__init__.py's get_provider() for the swap point.
"""


class Provider:
    def generate_image(self, prompt: str, image_paths: list = None, **options) -> dict:
        """image_paths=None -> text-to-image; image_paths=[...] -> edit
        those images with `prompt`. Returns {"images": [{"local_path",
        "url", "width", "height", "content_type"}, ...], "description"}."""
        raise NotImplementedError

    def generate_video(self, prompt: str, image_path: str, **options) -> dict:
        """Animates a single starting image. Returns {"video": {"local_path",
        "url", "content_type", "file_size"}}."""
        raise NotImplementedError
