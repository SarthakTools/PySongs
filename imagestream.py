# import requests
# from PIL import Image
# import io, time, functools, queue
# import customtkinter as ctk
# from threading import Lock
# from concurrent.futures import ThreadPoolExecutor

# class GitHubImageLoader:
#     def __init__(self, url: str):
#         self.url = url
#         self._cache = {}
#         self._lock = Lock()

#     @functools.lru_cache(maxsize=100)  # In-memory cache
#     def fetch_image(self, width=300, height=300):
#         with self._lock:  # Prevent concurrent spam
#             # Small backoff to be nice to GitHub
#             time.sleep(0.08)  # ~80ms delay between requests
            
#             for attempt in range(3):  # Retry up to 3 times
#                 try:
#                     response = requests.get(self.url, timeout=8)
#                     response.raise_for_status()
                    
#                     pil_image = Image.open(io.BytesIO(response.content))
#                     ctk_image = ctk.CTkImage(
#                         light_image=pil_image,
#                         size=(width, height)
#                     )
#                     return ctk_image
                    
#                 except requests.exceptions.HTTPError as e:
#                     if e.response.status_code == 400 and attempt < 2:
#                         time.sleep(0.3 * (attempt + 1))  # exponential backoff
#                         continue
#                     else:
#                         print(f"Failed to load image {self.url} -> {e}")
#                         break
#                 except Exception as e:
#                     print(f"Image load error {self.url}: {e}")
#                     break
            
#             # Return a fallback (transparent or default image)
#             fallback = ctk.CTkImage(
#                 light_image=Image.new("RGBA", (width, height), (50, 50, 50, 100)),
#                 size=(width, height)
#             )
#             return fallback

# class App:
#     def __init__(self, root):
#         self.root = root
#         self.root.title("GitHub Image Viewer")
#         self.root.geometry("400x400")

#         self.current_image = None

#         self.label = ctk.CTkLabel(root, text="")
#         self.label.pack(padx=20, pady=20, expand=True)

#         self.url = "https://raw.githubusercontent.com/SarthakTools/music/main/singersImage/alan_walker.png"
#         self.loader = GitHubImageLoader(self.url)
        
#         self.current_image = self.loader.fetch_image(width=300, height=300)
#         self.label.configure(image=self.current_image)


# if __name__ == "__main__":
#     ctk.set_appearance_mode("dark")    
#     ctk.set_default_color_theme("blue")    
    
#     root = ctk.CTk()
#     app = App(root)
#     root.mainloop()

import hashlib
import io
import os
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

import customtkinter as ct
import requests
from PIL import Image


CACHE_ROOT = Path(r"C:\cookies\PyMusic\assets")
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

_RAW_HOST = "raw.githubusercontent.com"
_cache_lock = threading.Lock()
_image_cache = {}


class GitHubImageLoader:
    """
    Loads images from the local PyMusic cache first.

    Existing usage remains unchanged:

        image = GitHubImageLoader(url).fetch_image(40, 40)

    For this repository:
        https://raw.githubusercontent.com/SarthakTools/music/main/images/home.png

    local path becomes:
        C:\\cookies\\PyMusic\\assets\\images\\home.png
    """

    def __init__(self, url):
        self.url = url
        self.local_path = self._get_local_path(url)

    @staticmethod
    def _get_local_path(url):
        parsed = urlparse(url)

        if parsed.scheme in ("", "file"):
            return Path(unquote(parsed.path))

        path_parts = unquote(parsed.path).lstrip("/").split("/")

        # Raw GitHub path:
        # /OWNER/REPO/BRANCH/repository/file/path.png
        if parsed.netloc == _RAW_HOST and len(path_parts) >= 4:
            repository_path = path_parts[3:]
            return CACHE_ROOT.joinpath(*repository_path)

        # Fallback for any other image URL.
        filename = Path(unquote(parsed.path)).name
        if not filename:
            filename = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".img"

        return CACHE_ROOT / "_external" / filename

    def _download_if_missing(self):
        if self.local_path.exists() and self.local_path.stat().st_size > 0:
            return self.local_path

        self.local_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(
            self.url,
            timeout=25,
            stream=True,
            headers={"User-Agent": "PyMusic"},
        )
        response.raise_for_status()

        temporary = self.local_path.with_suffix(
            self.local_path.suffix + ".part"
        )

        with temporary.open("wb") as file:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    file.write(chunk)

        temporary.replace(self.local_path)
        return self.local_path

    def fetch_pil_image(self):
        """
        Returns a detached PIL image.

        This method is safe to call from a worker thread because it does not
        create any Tkinter or CustomTkinter object.
        """
        with _cache_lock:
            path = self._download_if_missing()

        with Image.open(path) as source:
            return source.convert("RGBA").copy()

    def fetch_image(self, width=None, height=None):
        """
        Returns CTkImage while preserving your old method signature.

        Call this method on the Tkinter main thread. The installer should
        already have downloaded the file, so this normally reads only from disk.
        """
        width = int(width or 40)
        height = int(height or width)

        cache_key = (str(self.local_path), width, height)

        cached = _image_cache.get(cache_key)
        if cached is not None:
            return cached

        pil_image = self.fetch_pil_image()
        ctk_image = ct.CTkImage(
            light_image=pil_image,
            dark_image=pil_image,
            size=(width, height),
        )

        _image_cache[cache_key] = ctk_image
        return ctk_image

    @staticmethod
    def clear_memory_cache():
        _image_cache.clear()