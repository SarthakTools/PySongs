import requests
import time
import functools
from threading import Lock

# Simple in-memory cache
_data_cache = {}
_cache_lock = Lock()
 


def _fetch_data_with_retry(url: str, max_retries=3):
    """Internal helper with retry + backoff"""
    with _cache_lock:
        if url in _data_cache:
            return _data_cache[url]

        for attempt in range(max_retries):
            try:
                time.sleep(0.1 * attempt)  # small backoff
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                content = response.text
                _data_cache[url] = content  # cache raw text
                return content

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 400 and attempt < max_retries - 1:
                    time.sleep(0.4 * (attempt + 1))  # backoff
                    continue
                else:
                    print(f"Data fetch failed ({attempt+1}/{max_retries}): {e}")
                    break
            except Exception as e:
                print(f"Unexpected error fetching data: {e}")
                break

        # Return None if all attempts failed
        return None


def get_singer_data():
    try:
        url = "https://raw.githubusercontent.com/SarthakTools/music/main/data/singer_data.py"
        content = _fetch_data_with_retry(url)
        
        if not content:
            return "Loading"

        start = content.find('artists_data =')
        if start == -1:
            return "Loading"
        
        local_dict = {}
        exec(content, {"__builtins__": {}}, local_dict)
        return local_dict.get('artists_data', "Loading")
        
    except Exception as e:
        print(f"Error in get_singer_data: {e}")
        return "Loading"


def get_music_data():
    try:
        url = "https://raw.githubusercontent.com/SarthakTools/music/main/data/singer_data.py"
        content = _fetch_data_with_retry(url)
        
        if not content:
            return []

        start = content.find('music_details =')
        if start == -1:
            return []
        
        local_dict = {}
        exec(content, {"__builtins__": {}}, local_dict)
        return local_dict.get('music_details', [])
        
    except Exception as e:
        print(f"Error in get_music_data: {e}")
        return []


def get_song_data():
    try:
        url = "https://raw.githubusercontent.com/SarthakTools/music/main/data/singer_data.py"
        content = _fetch_data_with_retry(url)
        
        if not content:
            return {}
        
        start = content.find('singer_data =')
        if start == -1:
            return {}
        
        local_dict = {}
        exec(content, {"__builtins__": {}}, local_dict)
        return local_dict.get('singer_data', {})
        
    except Exception as e:
        print(f"Error in get_song_data: {e}")
        return {}


# Optional: Clear cache if needed
def clear_data_cache():
    global _data_cache
    with _cache_lock:
        _data_cache.clear()


if __name__ == "__main__":
    artists = get_singer_data()
    singer = get_song_data()
    print(f"Total singers: {len(artists) if isinstance(artists, list) else 'Error'}")
    print("Sample artists loaded successfully.")