import os
import tempfile
import threading
import requests
from just_playback import Playback

class AudioStream:
    def __init__(self):
        self.player = Playback()
        self.songs = []                 # list of local temp file paths
        self.urls = []                  # original URLs (for reference)
        self.current_index = 0
        self._temp_files = []           # so we can clean them later
        self._lock = threading.Lock()

    def _download(self, url: str) -> str:
        """Download URL to a temporary .mp3 file and return the path"""
        try:
            response = requests.get(url, timeout=15, stream=True)
            response.raise_for_status()

            # Create a unique temp file
            fd, path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)

            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self._temp_files.append(path)
            return path
        except Exception as e:
            print(f"Download failed: {url} → {e}")
            return None

    def load_single(self, url: str):
        self.stop()
        self.urls = [url]
        self.current_index = 0

        local = self._download(url)
        if local:
            self.songs = [local]
            self.player.load_file(local)
        else:
            self.songs = []

    def load_playlist(self, song_list: list):
        self.stop()
        self.urls = song_list
        self.current_index = 0
        self.songs = []

        for url in song_list:
            local = self._download(url)
            if local:
                self.songs.append(local)

        if self.songs:
            self.player.load_file(self.songs[0])

    def play(self):
        if self.songs:
            self.player.play()

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def stop(self):
        try:
            self.player.stop()
        except:
            pass
        self.current_index = 0

    def next(self):
        if not self.songs:
            return
        if self.current_index < len(self.songs) - 1:
            self.current_index += 1
            self.player.load_file(self.songs[self.current_index])
            self.player.play()

    def previous(self):
        if not self.songs:
            return
        if self.current_index > 0:
            self.current_index -= 1
            self.player.load_file(self.songs[self.current_index])
            self.player.play()

    def get_duration(self):
        # just_playback returns seconds → convert to milliseconds for compatibility
        try:
            return int(self.player.duration * 1000)
        except:
            return 0

    def get_current_time(self):
        try:
            return int(self.player.curr_pos * 1000)
        except:
            return 0

    def format_time(self, ms):
        if ms < 0:
            return "00:00"
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def seek(self, ms: int):
        """Seek to position in milliseconds"""
        try:
            self.player.seek(ms / 1000.0)
        except:
            pass

    def cleanup(self):
        """Call this when the app closes"""
        self.stop()
        for f in self._temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass
        self._temp_files.clear()

    def __del__(self):
        self.cleanup()