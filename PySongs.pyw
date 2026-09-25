import os, time, random, threading, string, queue, shutil
from CTkToolTip import CTkToolTip
import customtkinter as ct
from customtkinter import *
from CTkXYFrame import CTkXYFrame
from ctypes import windll
from CTkMessagebox import CTkMessagebox
from audiostream import AudioStream
from imagestream import GitHubImageLoader
from datastream import get_singer_data, get_song_data, get_music_data
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities
import asyncio, json
from pathlib import Path
from urllib.parse import quote
import requests

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

OWNER = "SarthakTools"
REPO = "music"
BRANCH = "main"

MAX_DOWNLOAD_WORKERS = min(8, max(2, (os.cpu_count() or 4)))

BASE_DIR = Path(r"C:\cookies\PyMusic")
ASSET_DIR = BASE_DIR / "assets"
MANIFEST_FILE = BASE_DIR / "image_manifest.json"

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico"
}

API_TREE_URL = (
    f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{BRANCH}?recursive=1"
)
RAW_BASE_URL = (
    f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/"
)


class PyMusicInstaller:
    def __init__(self, root):
        self.root = root
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.title("PyMusic Image Installer")
        self.root.geometry("650x420")
        self.root.resizable(False, False)

        self.events = queue.Queue()
        self.running = False

        BASE_DIR.mkdir(parents=True, exist_ok=True)
        ASSET_DIR.mkdir(parents=True, exist_ok=True)

        # Wrap installer UI in a frame so we can cleanly remove it
        # when transitioning to the IntroPage after installation.
        self.installer_frame = ct.CTkFrame(self.root, fg_color="transparent")
        self.installer_frame.pack(fill="both", expand=True)

        ct.CTkLabel(
            self.installer_frame,
            text="PyMusic Image Installer",
            font=("Poppins", 30, "bold"),
        ).pack(pady=(30, 8))

        ct.CTkLabel(
            self.installer_frame,
            text="Downloads and synchronizes image assets from GitHub.",
            font=("Poppins", 15),
        ).pack(pady=(0, 25))

        self.status_label = ct.CTkLabel(
            self.installer_frame,
            text="Ready",
            font=("Consolas", 15),
            wraplength=580,
        )
        self.status_label.pack(pady=10)

        self.progress = ct.CTkProgressBar(self.installer_frame, width=540)
        self.progress.pack(pady=15)
        self.progress.set(0)

        self.counter_label = ct.CTkLabel(
            self.installer_frame,
            text="0 / 0",
            font=("Consolas", 14),
        )
        self.counter_label.pack()

        self.install_button = ct.CTkButton(
            self.installer_frame,
            text="Install / Sync Images",
            height=45,
            font=("Poppins", 17, "bold"),
            command=self.start_sync,
        )
        self.install_button.pack(pady=25)

        self.path_label = ct.CTkLabel(
            self.installer_frame,
            text=f"Cache folder:\n{ASSET_DIR}",
            font=("Consolas", 13),
        )
        self.path_label.pack(pady=5)

        self.after_ids = set()

        t_id = self.root.after(100, self.process_events)
        self.after_ids.add(t_id)

    def on_close(self):
        for ids in self.after_ids:
            try:
                self.root.after_cancel(ids)
            except Exception:
                pass
        self.root.destroy()

    def start_sync(self):
        if self.running:
            return

        self.running = True
        self.install_button.configure(state="disabled")
        self.progress.set(0)
        self.counter_label.configure(text="0 / 0")
        self.status_label.configure(text="Reading GitHub repository...")

        threading.Thread(
            target=self.sync_worker,
            daemon=True,
        ).start()

    @staticmethod
    def load_manifest():
        if not MANIFEST_FILE.exists():
            return {}

        try:
            with MANIFEST_FILE.open("r", encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def save_manifest(manifest):
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = MANIFEST_FILE.with_suffix(".tmp")

        with temporary.open("w", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2)

        temporary.replace(MANIFEST_FILE)

    @staticmethod
    def fetch_repository_images():
        response = requests.get(
            API_TREE_URL,
            timeout=30,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "PyMusic-Installer",
            },
        )
        response.raise_for_status()

        result = []
        for item in response.json().get("tree", []):
            if item.get("type") != "blob":
                continue

            repo_path = item.get("path", "")
            if Path(repo_path).suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            result.append({
                "path": repo_path,
                "sha": item.get("sha", ""),
                "size": item.get("size", 0),
            })

        return result

    @staticmethod
    async def fetch_image_async(session, repo_path):
        destination = ASSET_DIR / Path(repo_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        encoded_path = quote(repo_path, safe="/")
        url = RAW_BASE_URL + encoded_path

        temporary = destination.with_suffix(destination.suffix + ".part")

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
            response.raise_for_status()
            with temporary.open("wb") as file:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    file.write(chunk)

        temporary.replace(destination)
        return destination

    @staticmethod
    def download_image(repo_path):
        if aiohttp is None:
            return PyMusicInstaller.download_image_sync(repo_path)

        raise RuntimeError("download_image should not be called in async mode")

    @staticmethod
    def download_image_sync(repo_path):
        destination = ASSET_DIR / Path(repo_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        encoded_path = quote(repo_path, safe="/")
        url = RAW_BASE_URL + encoded_path

        response = requests.get(
            url,
            timeout=30,
            stream=True,
            headers={"User-Agent": "PyMusic-Installer"},
        )
        response.raise_for_status()

        temporary = destination.with_suffix(destination.suffix + ".part")

        with temporary.open("wb") as file:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    file.write(chunk)

        temporary.replace(destination)
        return destination

    async def sync_images_async(self, images, old_manifest):
        if aiohttp is None:
            raise RuntimeError("aiohttp is required for async downloads")

        new_manifest = {}
        downloaded = 0
        skipped = 0
        completed = 0
        total = len(images)
        pending_downloads = []

        for image in images:
            repo_path = image["path"]
            sha = image["sha"]
            destination = ASSET_DIR / Path(repo_path)
            previous = old_manifest.get(repo_path, {})
            unchanged = (
                destination.exists()
                and previous.get("sha") == sha
            )

            new_manifest[repo_path] = {
                "sha": sha,
                "size": image["size"],
            }

            if unchanged:
                skipped += 1
                completed += 1
                self.events.put(("status", f"Already cached: {repo_path}"))
                self.events.put(("progress", completed, total))
                continue

            pending_downloads.append(repo_path)

        if not pending_downloads:
            return new_manifest, downloaded, skipped

        connector = aiohttp.TCPConnector(limit=MAX_DOWNLOAD_WORKERS)
        headers = {"User-Agent": "PyMusic-Installer"}

        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            sem = asyncio.Semaphore(MAX_DOWNLOAD_WORKERS)

            async def bound_download(path):
                nonlocal completed, downloaded
                async with sem:
                    self.events.put(("status", f"Downloading: {path}"))
                    await self.fetch_image_async(session, path)
                    downloaded += 1
                    completed += 1
                    self.events.put(("progress", completed, total))

            downloads = [bound_download(path) for path in pending_downloads]
            for future in asyncio.as_completed(downloads):
                await future

        return new_manifest, downloaded, skipped

    def sync_worker(self):
        try:
            old_manifest = self.load_manifest()
            images = self.fetch_repository_images()
            total = len(images)

            self.events.put(("total", total))

            if aiohttp is not None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    new_manifest, downloaded, skipped = loop.run_until_complete(
                        self.sync_images_async(images, old_manifest)
                    )
                finally:
                    loop.close()
            else:
                new_manifest = {}
                downloaded = 0
                skipped = 0
                for index, image in enumerate(images, start=1):
                    repo_path = image["path"]
                    sha = image["sha"]
                    destination = ASSET_DIR / Path(repo_path)

                    previous = old_manifest.get(repo_path, {})
                    unchanged = (
                        destination.exists()
                        and previous.get("sha") == sha
                    )

                    if unchanged:
                        skipped += 1
                        self.events.put((
                            "status",
                            f"Already cached: {repo_path}",
                        ))
                    else:
                        self.events.put((
                            "status",
                            f"Downloading: {repo_path}",
                        ))
                        self.download_image_sync(repo_path)
                        downloaded += 1

                    new_manifest[repo_path] = {
                        "sha": sha,
                        "size": image["size"],
                    }
                    self.events.put(("progress", index, total))

            self.save_manifest(new_manifest)
            self.events.put(("done", downloaded, skipped, total))

        except Exception as error:
            self.events.put(("error", str(error)))

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                event_type = event[0]

                if event_type == "total":
                    total = event[1]
                    self.counter_label.configure(text=f"0 / {total}")

                elif event_type == "status":
                    self.status_label.configure(text=event[1])

                elif event_type == "progress":
                    current, total = event[1], event[2]
                    self.progress.set(current / total if total else 0)
                    self.counter_label.configure(
                        text=f"{current} / {total}"
                    )

                elif event_type == "downloaded":
                    _, _, path = event
                    self.status_label.configure(text=f"Downloaded: {path}")

                elif event_type == "done":
                    downloaded, skipped, total = event[1:]
                    self.running = False
                    self.install_button.configure(state="normal")
                    self.status_label.configure(
                        text=(
                            "Sync completed.\n"
                            f"Downloaded: {downloaded} | "
                            f"Already cached: {skipped} | "
                            f"Total: {total}\n"
                            "Starting PyMusic..."
                        )
                    )
                    # Transition to IntroPage in the same window after a brief delay
                    t_id = self.root.after(1500, self.launch_intro)
                    self.after_ids.add(t_id)

                elif event_type == "error":
                    self.running = False
                    self.install_button.configure(state="normal")
                    self.status_label.configure(
                        text=f"Installation failed:\n{event[1]}"
                    )

        except queue.Empty:
            pass

        t_id = self.root.after(100, self.process_events)
        self.after_ids.add(t_id)

    def launch_intro(self):
        """Clean up the installer UI and start the IntroPage in the same window."""
        # Cancel any pending after callbacks
        for ids in self.after_ids:
            try:
                self.root.after_cancel(ids)
            except Exception:
                pass
        self.after_ids.clear()

        # Remove the installer frame
        try:
            self.installer_frame.destroy()
        except Exception:
            pass

        # Run IntroPage in the same root window
        setup_files()
        write_defaults()

        IntroPage(self.root)


ct.set_default_color_theme("green")
ct.set_appearance_mode("dark")

def setup_files():
    folder_name = "cookies"
    filename = ["avatar_name.txt", "password.txt", "user-name.txt"]

    base_dir =f"C:\\{folder_name}"
    if  os.path.isdir(base_dir):
        pass
    else:
        try:
            os.mkdir(f"C:\\{folder_name}")
        except:
            pass
            
    for file in filename:
            # Create the full path for the specific file
            file_path = os.path.join(base_dir, file)
            
            # Check if the specific file exists, not the folder
            if os.path.isfile(file_path):
                pass
            else:
                try:
                    with open(file_path, "x+") as f:
                        pass
                    pass
                except Exception:
                    pass

def write_defaults():
    folder_name = "cookies"
    filename = ["avatar_name.txt", "password.txt", "user-name.txt"]
    with open(f"C:\\{folder_name}\\{filename[0]}", "w") as avatar_name:
        avatar_name.write("avatar/avator20.png")
    with open(f"C:\\{folder_name}\\{filename[1]}", "w") as password:
        password.write("123456")
    with open(f"C:\\{folder_name}\\{filename[2]}", "w") as uname:
        uname.write("python-default")

def clean_files():
    pass

class IntroPage:
    def __init__(self, root):
        self.root = root
        self.root.title("PyMusic - A modern music player built with Python")
        self.root.geometry("550x300")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        pymusic_image = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/pymusic.png").fetch_image(100, 100)

        ct.CTkLabel(self.root, text=" PyMusic", image=pymusic_image, text_color="white", compound=LEFT, font=("Poppins", 60, "bold")).pack(padx=10, pady=120, anchor="center")
    
        self.text = ct.CTkLabel(self.root, text="Please wait...The First launch of the app may take longer...", font=("IBM Plex Sans", 15))
        self.progressbar = ct.CTkProgressBar(self.root, orientation="horizontal", width=300, mode="determinate", determinate_speed=0.35, 
                                             fg_color="white", height=8, progress_color="#1ED765", corner_radius=0)
        self.progressbar.pack(side=BOTTOM, fill=X)
        self.text.pack(side=BOTTOM, anchor="center")
        
        self.progressbar.set(0)
        self.progressbar.start()

        self.thread = threading.Thread(target=self.loading)
        self.thread.start()
        self.set_appwindow(self.root)
        self.center_window(self.root)

    def loading(self):
        time.sleep(4)
        self.text.configure(text="")
        self.text.configure(text="Please wait.....The First launch of the app may take longer...")
        self.progressbar.stop()
        self.progressbar.set(100)
        self.main()
    
    def center_window(self, win):
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
        win.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def set_appwindow(self, mainWindow): 
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        hwnd = windll.user32.GetParent(mainWindow.winfo_id())
        stylew = windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        stylew = stylew & ~WS_EX_TOOLWINDOW
        stylew = stylew | WS_EX_APPWINDOW
        res = windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, stylew)   
        mainWindow.wm_withdraw()
        mainWindow.after(10, lambda: mainWindow.wm_deiconify())

    def main(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        threading.Thread(target=lambda:  LoginPage(root)).start()

class LoginPage:
    """Typewriter welcome text, then reveal the login UI with a slide animation."""
    def __init__(self, root, text: str = "Welcome to PyMusic", speed: int = 60):
        self.root = root
        self.root.configure(fg_color="black")
        self.root.attributes("-topmost", False)
        self.root.overrideredirect(False)
        self.root.geometry("1000x600+200+40")
        set_default_color_theme("dark-blue")
        self.root.resizable(False, False)
        self.root.title("Login Page")
        self.text = text
        self.speed = speed
        self.idx = 0

        # white text on black background (no red)
        self.label = CTkLabel(root, text="", font=("monospace", 48, "bold"),
                              text_color="white", fg_color="black")
        self.label.place(relx=0.5, rely=0.20, anchor="center")

        self.root.after(300, self._type)

    def _type(self):
        if self.idx < len(self.text):
            current = self.label.cget("text") + self.text[self.idx]
            self.label.configure(text=current)
            self.idx += 1
            self.root.after(self.speed, self._type)
        else:
            self.root.after(450, self._reveal_login)

    def _reveal_login(self):
        # Keep the welcome title fixed at top, then show staged credential inputs.
        # Don't destroy the label — resize/reposition it to top.
        try:
            self.label.place_configure(relx=0.5, rely=0.12)
            self.label.configure(font=("monospace", 36, "bold"))
        except Exception:
            pass

        flow = EmailPasswordFlow(self.root, title_label=self.label)
        flow.show_email_stage()

class EmailPasswordFlow:
    def __init__(self, root, title_label: CTkLabel = None):
        self.root = root
        self.title_label = title_label
        self.email_frame = None
        self.password_frame = None
        self.email_var = StringVar()
        self.pass_var = StringVar()

        self.root.configure(fg_color="#000")
        self.eyes_icon_open = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/eyes_open.png").fetch_image(20, 20)
        self.eyes_icon_closed =  GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/eyes_closed.png").fetch_image(20, 20)
        self.gen_image =  GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/innovation.png").fetch_image(32, 32)

    def _slide(self, widget, start_x, end_x, steps=20, delay=12):
        def step(i):
            if i > steps:
                widget.place_configure(x=end_x)
                return
            x = int(start_x + (end_x - start_x) * (i / steps))
            widget.place_configure(x=x)
            self.root.after(delay, lambda: step(i + 1))

        step(0)

    def show_email_stage(self):
        w = self.root.winfo_width() or 1000
        h = self.root.winfo_height() or 600
        # center position
        cx = int(w / 2)
        cy = int(h * 0.45)

        # desired frame size
        fw = 480
        fh = 160
        Height = 22
        Width = 380

        # create frame for email input (pass width/height to constructor)
        self.email_frame = CTkFrame(self.root, fg_color="#111", corner_radius=12, width=fw, height=fh)

        CTkLabel(self.email_frame, text="Username", font=("monospace", 20, "bold"), text_color="white").pack(pady=(20, 6), anchor="nw", padx=(20, 0))

        self.email_entry = CTkEntry(self.email_frame, placeholder_text="Email or username", font=("monospace", 18, "bold"), 
                                         height=Height, width=Width, text_color="#dedede", fg_color="#0A0A0A", border_width=0, textvariable=self.email_var)
        self.email_entry.pack(padx=20, pady=(4, 4), ipady=10, ipadx=105)

        self.generate_eyes = ct.CTkButton(self.email_frame, text="", image=self.gen_image, width=0, font=("consolas", 100), fg_color="transparent", hover_color="#202124", command=self.generate_guest_name)
        self.generate_eyes.pack(padx=(0, 20), pady=(0, 0), side="right", anchor="e")
        
        self.submit_btn = CTkButton(self.email_frame, text="Next", command=self._on_email_submit, width=0, font=("monospace", 18, "bold"))
        self.submit_btn.pack(pady=(10, 16), ipadx=40, ipady=5)

        start_x = w + 20
        end_x = cx - int(fw / 2)
        place_y = cy - int(fh / 2) - 40
        self.email_frame.place(x=start_x, y=place_y)
        self._slide(self.email_frame, start_x, end_x-80, steps=18, delay=12)

    def _on_email_submit(self):
        email = self.email_var.get().strip()
        if not email:
            CTkMessagebox(title="Error", message="Please enter your email.", icon="cancel")
            return
        w = self.root.winfo_width() or 1000
        fw = self.email_frame.winfo_width()
        start_x = self.email_frame.winfo_x()
        target_x = -fw - 50
        self._slide(self.email_frame, start_x, target_x, steps=18, delay=12)
        
        with open("C:\\cookies\\user-name.txt", "w") as f:
            f.write(email)

        self.root.after(350, self.show_password_stage)

    def show_password_stage(self):
        w = self.root.winfo_width() or 1000
        h = self.root.winfo_height() or 600
        cx = int(w / 2)
        cy = int(h * 0.45)
        fw = 480
        fh = 160
        Height = 22
        Width = 380

        self.password_frame = CTkFrame(self.root, fg_color="#111", corner_radius=12, width=fw, height=fh)
        CTkLabel(self.password_frame, text="Password", font=("monospace", 20, "bold"), text_color="white").pack(pady=(20, 6), anchor="nw", padx=(20, 0))

        self.pass_entry = CTkEntry(self.password_frame, textvariable=self.pass_var, placeholder_text="Password",
                              font=("monospace", 18, "bold"), height=Height, width=Width,
                              text_color="#dedede", fg_color="#0A0A0A", border_width=0, show="*")
        self.pass_entry.pack(padx=20, pady=(4, 4), ipady=10, ipadx=105)

        def toggle_show():
            if self.pass_entry.cget("show") == "":
                self.pass_entry.configure(show="*")
                self.icon_eyes.configure(image=self.eyes_icon_closed)
            else:
                self.pass_entry.configure(show="")
                self.icon_eyes.configure(image=self.eyes_icon_open)

        self.icon_eyes = ct.CTkButton(self.password_frame, text="", image=self.eyes_icon_closed, width=0, font=("consolas", 100), fg_color="transparent", hover_color="#202124", command=toggle_show)
        self.icon_eyes.pack(padx=(0, 10), pady=(0, 0), side="right", anchor="e")

        self.icon_gen = ct.CTkButton(self.password_frame, text="", image=self.gen_image, width=0, font=("consolas", 100), fg_color="transparent", hover_color="#202124", 
                    command=self.generate_password)
        self.icon_gen.pack(padx=(0, 0), pady=(0, 0), side="right", anchor="e")
        
        self.submit_btn = CTkButton(self.password_frame, text="Next", command=self._on_password_submit, width=0, font=("monospace", 18, "bold"))
        self.submit_btn.pack(pady=(10, 16), ipadx=40, ipady=5)

        start_x = w + 20
        end_x = cx - int(fw / 2)
        place_y = cy - int(fh / 2) - 40
        self.password_frame.place(x=start_x, y=place_y)
        self._slide(self.password_frame, start_x, end_x-80, steps=18, delay=12)

    def generate_password(self):
        chars = string.ascii_letters + string.digits
        n_password =  "" + "".join(random.choice(chars) for _ in range(8))
        self.pass_var.set(n_password)
        self.pass_entry.delete(0, END)
        self.pass_entry.insert(0, n_password)

    def _on_password_submit(self):
        self.submit_btn.configure(state="disabled")
        self.icon_gen.configure(state="disabled")
        self.pass_entry.configure(state="disabled")

        pwd = self.pass_var.get().strip()
        if not pwd:
            CTkMessagebox(title="Error", message="Please enter your password.", icon="cancel")
            return

        with open("C:\\cookies\\password.txt", "w") as f:
            f.write(pwd)

        self.root.update_idletasks()
        dots_frame = CTkFrame(self.root, fg_color="transparent")
        dots_frame.place(relx=0.5, rely=0.92, anchor="center")
        dots_frame.lift()

        dot_font = ("monospace", 48, "bold")
        dots = []
        for i in range(4):
            lbl = CTkLabel(dots_frame, text="●", font=dot_font, text_color="#4a4a4a", fg_color="transparent")
            lbl.pack(side=LEFT, padx=8)
            dots.append(lbl)

        duration = 5.0  # seconds to run the animation
        start_time = time.time()

        def tick(counter=0):
            elapsed = time.time() - start_time
            if elapsed >= duration:
                # finish: open MainPage
                global user_name
                user_name = self.email_var.get().strip()
                for w in self.root.winfo_children():
                    w.destroy()
                threading.Thread(target=lambda:  AvatorPage(self.root)).start()
                return

            # determine active dot (0..3) and update visual state
            active = counter % 4
            for idx, d in enumerate(dots):
                if idx == active:
                    d.configure(text="●", text_color="#FFFFFF")
                else:
                    # dim the inactive dots so active one stands out
                    d.configure(text="●", text_color="#4a4a4a")

            # schedule next frame (~350ms for a clear sequential blink)
            self.root.after(350, lambda: tick(counter + 1))

        # start animation loop
        tick(0)

    def generate_guest_name(self):
        chars = string.ascii_letters + string.digits
        new_name =  "python-" + "".join(random.choice(chars) for _ in range(4))
        self.email_var.set(new_name)
        self.email_entry.delete(0, END)
        self.email_entry.insert(0, new_name)

class AvatorPage:
    def __init__(self, root):
        self.root = root
        self.root.configure(fg_color="black")
        self.root.geometry("1000x650+400+87")
        self.root.resizable(False, False)
        set_default_color_theme("dark-blue")

        self.imgSize_big = (400, 400)
        self.imgSize_small = (40, 40)

        self.selected_avatar = None
        self.avatars = []

        # MAIN FRAME
        self.mainFrame = ct.CTkFrame(self.root, fg_color="black")
        self.mainFrame.pack(fill=BOTH, expand=True)

        # ================= BIG AVATAR (TOP CENTER) =================
        self.previewFrame = ct.CTkFrame(self.mainFrame, fg_color="black")
        self.previewFrame.pack(pady=50)

        self.previewLabel = ct.CTkLabel(self.previewFrame, text="", fg_color="black")
        self.previewLabel.pack()

        self.avatarBar = ct.CTkFrame(self.mainFrame, fg_color="transparent")
        self.avatarBar.pack(side=BOTTOM, fill=X, padx=70, pady=10)
        self.avatarBar.pack_propagate(False)
        self.avatarBar.configure(width=700, height=60)
        for i in range(17, 26):
            img_path = f"avatar/avator{i}.png"
            img = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/avatar/avator{i}.png").fetch_image(60, 60)
            big_img = img
            hover_img = img
            normal_img = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/avatar/avator{i}.png").fetch_image(50, 50)

            self.avatars.append((normal_img, hover_img, big_img))
            btn = ct.CTkButton(
                self.avatarBar,
                text="",
                image=normal_img,
                fg_color="transparent",
                hover_color="#222", width=80, height=80,
                command=lambda p=img_path: self.selectAvatar(p)
            )
            btn.pack(side=LEFT, padx=7)
            btn.bind("<Enter>", lambda e, b=btn, i=hover_img: b.configure(image=i))
            btn.bind("<Leave>", lambda e, b=btn, i=normal_img: b.configure(image=i))

        # ================= NEXT BUTTON =================
        self.nextButton = ct.CTkButton(
            self.root,
            text="Next", text_color="white",
            font=("Lucida Console", 18),
            state="disabled",
            command=self.getPyMusicApp)

        self.nextButton.pack(side=BOTTOM, anchor="center", pady=10, padx=10, ipadx=2, ipady=8)

    # ================= SELECT AVATAR =================
    def selectAvatar(self,  path):
        self.selected_avatar = path
        path = path.replace("\\", "/")
        img = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/{path}").fetch_image(300, 300)
        self.previewLabel.configure(image=img)
        self.previewLabel.image = img
        self.nextButton.configure(state="normal")

        with open("C:\\cookies\\avatar_name.txt", "w") as f:
            f.write(path)

    def getPyMusicApp(self):
        self.mainFrame.destroy()
        self.nextButton.destroy()
        threading.Thread(target=self.show_PyMusic).start()
        
    def show_PyMusic(self):
        threading.Thread(target=lambda: PyMusic(self.root)).start()

class PyMusic:
    def __init__(self, root):
        self.root = root
        self.root.title("PyMusic")
        self.root.geometry("1300x700+100+80")
        self.root.minsize(1300, 700)
        self.bg_color = "#262626"
        self.root.configure(fg_color=self.bg_color)
        self.root.resizable(True, True)
        set_default_color_theme("green")


        self._startup_queue = queue.Queue()
        self._loading_music = False
        self._music_loaded = False
        self._artists_loaded = False
        self._artists_loading = False
        self._last_song_ui = None
        self._last_favourite_header = object()

        # Non-blocking play support
        self._song_data_cache = None
        self._play_queue = queue.Queue()
        self._is_loading_song = False
        self._current_play_id = 0

        self.pymusic_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/pymusic.png").fetch_image(70, 70)
        self.home_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/home.png").fetch_image(25, 25)
        self.discover_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/song.png").fetch_image(25, 25)
        self.rise_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/rise.png").fetch_image(25, 20)
        self.rise_img2 = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/search2.png").fetch_image(20, 20)
        self.settings_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/settings.png").fetch_image(25, 25)
        self.search_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/search.png").fetch_image(30, 30)
        self.add_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/plus.png").fetch_image(33, 33)
        self.delete_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/delete2.png").fetch_image(28, 28)
        self.edit_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/edit.png").fetch_image(28, 28)
        # self.favourite_img3 = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/star.png").fetch_image(28, 28)
        self.eyes_icon_open = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/eyes_open.png").fetch_image(20, 20)
        self.eyes_icon_closed = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/eyes_closed.png").fetch_image(20, 20)

        with open("C:\\cookies\\avatar_name.txt", "r") as f:
            profile_image = f.read()

        self.profile_img = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/{profile_image}").fetch_image(35, 35)
        self.avator_image = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/{profile_image}").fetch_image(155, 155) 
        
        self.nav_frame = ct.CTkFrame(self.root, fg_color="#222")

        self.PyMusic_label = ct.CTkLabel(self.nav_frame, text=" PyMusic      ", text_color="white", image=self.pymusic_img, compound=LEFT,
                                          font=("Poppins", 30))
        self.PyMusic_label.pack(side=TOP, padx=10, pady=5)

        ct.CTkLabel(self.nav_frame, text="").pack(pady=5)

        self.search = ct.CTkButton(self.nav_frame, text="Search", width=50, height=40, fg_color="transparent", hover_color="#444",
                                  corner_radius=10, image=self.search_img, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("search"))
        self.search.pack(side=TOP, pady=5, ipady=5, padx=5, fill=X)

        ct.CTkButton(self.nav_frame, text="", fg_color="transparent", hover_color="#222", text_color="white").pack(side=TOP, pady=10, fill=X)

        self.home = ct.CTkButton(self.nav_frame, text="Home", width=50, height=40, fg_color="transparent", hover_color="#444",
                                  corner_radius=10, image=self.home_img, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("home"))
        self.home.pack(side=TOP, pady=5, ipady=5, padx=5, fill=X)

        self.artists = ct.CTkButton(self.nav_frame, text="Artists", width=50, height=40, fg_color="transparent", hover_color="#444",
                                  corner_radius=10, image=self.discover_img, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("artists"))
        self.artists.pack(side=TOP, pady=5, ipady=5, padx=5, fill=X)

        self.trending = ct.CTkButton(self.nav_frame, text="Trending", width=50, height=40, fg_color="transparent", hover_color="#444",
                                  corner_radius=10, image=self.rise_img, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("trending"))
        self.trending.pack(side=TOP, pady=5, ipady=5, padx=5, fill=X)

        # self.favourites_btn = ct.CTkButton(self.nav_frame, text="Favourites", width=50, height=40, fg_color="transparent", hover_color="#444",
        #                           corner_radius=10, image=self.favourite_img3, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("favourites"))
        # self.favourites_btn.pack(side=TOP, pady=5, ipady=5, padx=5, fill=X)

        self.settings = ct.CTkButton(self.nav_frame, text="Settings", width=50, height=40, fg_color="transparent", hover_color="#444",
                                  corner_radius=10, image=self.settings_img, font=("Montserrat", 20), text_color="white", anchor="w", command=lambda: self.select_frame_name("settings"))
        self.settings.pack(side=BOTTOM, pady=10, ipady=5, padx=5, fill=X)

        self.nav_frame.pack(side=LEFT, fill=Y)

        self.main = ct.CTkFrame(self.root, corner_radius=0, fg_color=self.bg_color)
        self.main.pack(fill=BOTH, expand=True)

        # Create all the frames for every tab inside the main frame
        self.color_home_frame = "#333"

        # Search frame code here .........................
        self.search_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color="#555")
        self.search_label = ct.CTkLabel(self.search_frame, text="", image=self.search_img)

        self.search_box = ct.CTkEntry(self.search_frame, font=("IBM Plex Sans", 23), placeholder_text="What do you want to play today ?", placeholder_text_color="#a5a5a5",
                                       corner_radius=10, border_width=0, fg_color=self.bg_color, text_color="white")
        self.search_box.pack(side=TOP, fill=X, ipady=15, padx=20, pady=20)
        self.search_box.bind("<KeyRelease>", self.on_button_release)

        self.like_that_entry = ct.CTkEntry(self.search_frame, width=0, height=0, fg_color="#555", text_color="#555", bg_color="#555", border_width=0)
        self.like_that_entry.pack(side=BOTTOM, fill=X)
        self.search_frame.bind("<Button-1>", lambda event: self.like_that_entry.focus())

        song_data = get_music_data()
        self.all_songs_name = [s["name"] for s in song_data]

        self.searching_frame = ct.CTkFrame(self.search_frame, fg_color="#333")
        self.searching_frame.pack(side=TOP, fill=X, padx=20, pady=10)

        #----------------------------------------------------------------------------------------------------

        self.home_frame = CTkXYFrame(self.main, corner_radius=0, fg_color=self.color_home_frame)

        self.home_label = ct.CTkLabel(self.home_frame, text="Home", font=("Poppins", 50), text_color="white")
        self.home_label.pack(anchor="nw", side=TOP, padx=20)

        self.discover_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color="#1f1e42")
        self.popular_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color=self.color_home_frame)
        self.audiobooks_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color=self.color_home_frame)
        self.settings_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color=self.color_home_frame)
        # self.favourites_frame = ct.CTkFrame(self.main, corner_radius=0, fg_color=self.color_home_frame)


        ##################### ---------- Artists code ---------------- ###################################

        self.artist_frame = ct.CTkScrollableFrame(self.discover_frame, fg_color="transparent")
        self.artists_data = []
        ct.CTkLabel(self.discover_frame, text="Artists", font=("Helvetica", 55, "bold")).pack(side=TOP, anchor="ne", fill=X, pady=5)
        self.artist_loading_label = ct.CTkLabel(
            self.discover_frame,
            text="Open this tab to load artists",
            font=("IBM Plex Sans", 20)
        )
        self.artist_loading_label.pack(pady=30)

        # settings frame code ##################################

        self.profile_frame = ct.CTkFrame(self.settings_frame, fg_color=self.bg_color)
        self.profile_button = ct.CTkButton(self.profile_frame, text="", width=0, corner_radius=0, fg_color=self.bg_color, hover_color="#333", image=self.profile_img, command=self.changeProfilePhoto)
        self.profile_button.pack(side=RIGHT)

        self.profile_frame.pack(side=TOP, fill=X, ipady=10, padx=5, pady=2, ipadx=10)

        # settings control frame all the settings
        self.settings_control_frame = CTkScrollableFrame(self.settings_frame, fg_color=self.bg_color)
    
        ct.CTkLabel(self.settings_control_frame, text="Settings", font=("IBM Plex Sans", 40, "bold")).pack(side=TOP, anchor="nw", padx=20, pady=20)

        # account frame 
        self.account_frame = ct.CTkFrame(self.settings_control_frame)
        # self.account_frame = CTkScrollableFrame(self.settings_control_frame)

        self.account_details_frame = ct.CTkFrame(self.account_frame, fg_color="transparent")
        ct.CTkLabel(self.account_details_frame, text="Account", font=("Poppins", 30, "bold")).pack(side=TOP, anchor="nw", padx=10)
        
        details_frame = ct.CTkFrame(self.account_details_frame, fg_color="transparent")

        with open("C:\\cookies\\user-name.txt", "r") as f:
                self.email = f.read() 
        
        if self.email != "":
            pass
        else:
            self.email = "username@PyMusic.com"

        self.username = ct.CTkLabel(self.profile_frame, text=self.email, font=("IBM Plex Sans", 25, "bold"))
        self.username.pack(anchor="center", side=LEFT, padx=15)

        with open("C:\\cookies\\password.txt", "r") as p:
                self.password = p.read()
                
        if self.password != "":
            pass
        else:
            self.password = "12345678"

        self.email_label = ct.CTkLabel(details_frame, text=f"Username     :   {self.email}", font=("IBM Plex Sans", 20, "bold"))

        password_frame = ct.CTkFrame(details_frame, fg_color="transparent")
        self.password_label = ct.CTkLabel(password_frame, text=f"Password   :   ", font=("IBM Plex Sans", 20, "bold"))
        self.password_input = ct.CTkLabel(password_frame, font=("consolas", 20, "bold"), text="********")
        self.icon_eyes = ct.CTkButton(password_frame, text="", image=self.eyes_icon_closed, width=0, font=("consolas", 100), fg_color="transparent", hover_color=self.bg_color, command=self.show_password)
        self.password_label.pack(side=LEFT)
        self.password_input.pack(side=LEFT)
        self.icon_eyes.pack(side=LEFT, padx=5)

        self.email_label.pack(side=TOP, anchor="nw")
        password_frame.pack(side=TOP, anchor="nw")

        details_frame.pack(side=LEFT, pady=10, padx=10)
        self.account_details_frame.pack(side=LEFT, fill=BOTH, expand=True, pady=10, padx=10)

        self.photo_frame = ct.CTkLabel(self.account_frame, text="", image=self.avator_image, fg_color="transparent")
        self.photo_frame.pack(side=RIGHT, padx=40, fill=BOTH, ipadx=10, pady=10)        

        self.delete_account = ct.CTkButton(details_frame, text="Delete Account", font=("Poppins", 20, "bold"), fg_color="#e15455", hover_color="#f44344", corner_radius=10, bg_color="transparent", command=self.deleteAccount)
        self.delete_account.pack(side=TOP, anchor="nw", ipady=7, pady=5)

        self.account_frame.pack(side=TOP, fill=X, padx=15, ipady=10, pady=10)

        # ---------- Volume Control ----------
        # ---------- Windows System Volume ----------
        self.volume_frame = ct.CTkFrame(self.settings_control_frame)

        ct.CTkLabel(
            self.volume_frame,
            text="System Volume",
            font=("IBM Plex Sans", 20, "bold")
        ).pack(side=TOP, anchor="nw", padx=20, pady=(20, 10))

        self.volume_value_label = ct.CTkLabel(
            self.volume_frame,
            text="80%",
            font=("consolas", 15, "bold")
        )
        # self.volume_value_label.pack(side=TOP, anchor="nw", padx=25)

        self.volume_slider = ct.CTkSlider(
            self.volume_frame,
            from_=0,
            to=100,
            number_of_steps=100,
            height=20,
            progress_color="#1ED765",
            button_color="#1ED765",
            button_hover_color="#17b856",
            command=self.on_volume_change,
        )
        self.volume_slider.set(50)
        # self.volume_slider.pack(side=TOP, anchor="nw", padx=20)

        # self.volume_frame.pack(side=TOP, anchor="nw", fill=X, padx=15, pady=5, ipady=5)
        
        # about frame 
        self.about_frame = ct.CTkFrame(self.settings_control_frame)
        
        ct.CTkLabel(self.about_frame, text="About", font=("IBM Plex Sans", 40, "bold")).pack(side=TOP, anchor="nw", padx=20, pady=20)
        ct.CTkLabel(self.about_frame, text="About      : © 2024 PyMusic Limited. All rights reserved", font=("consolas", 20, "bold")).pack(side=TOP, anchor="nw", padx=20)
        ct.CTkLabel(self.about_frame, text="Version    : 1.1", font=("consolas", 20, "bold")).pack(side=TOP, anchor="nw", padx=20)
        ct.CTkLabel(self.about_frame, text="Developer  : Sarthak Singh", font=("consolas", 20, "bold")).pack(side=TOP, anchor="nw", padx=20)
    
        self.about_frame.pack(side=TOP, fill=BOTH, padx=15, pady=5, ipady=20)

        self.settings_control_frame.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=10)

        self.music_playing = None
        self.frames = {}  # Dictionary to store frames for each tab
        self.frames2 = {}  # Dictionary to store frames for each tab
        # control song frame
        
        # global stop_img, pause_img
        
        self.pause_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/pause.png").fetch_image(35, 35)
        self.stop_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/play.png").fetch_image(35, 35)
        self.skip_forward_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/skip-forward.png").fetch_image(35, 35)
        self.skip_backward_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/skip-back.png").fetch_image(35, 35)
        self.volume_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/volume.png").fetch_image(30, 30)
        self.volume_mute_img = GitHubImageLoader("https://raw.githubusercontent.com/SarthakTools/music/main/images/mute.png").fetch_image(30, 30)


        self.control_frame = ct.CTkFrame(self.root, corner_radius=10, fg_color="transparent")

        self.image_song_label = ct.CTkLabel(self.control_frame, text="", fg_color="#444", height=54, width=54, corner_radius=5)
        self.image_song_label.pack(side=LEFT, padx=10)

        self.slide_time_frame = ct.CTkFrame(self.control_frame, fg_color="transparent")

        self.time_elapsed_label = ct.CTkLabel(self.slide_time_frame, text="00:00", font=("Poppins", 20))
        self.time_elapsed_label.pack(side=LEFT, padx=10)

        self.music_duration_label = ct.CTkLabel(self.slide_time_frame, text="00:00", font=("Poppins", 20))
        self.music_duration_label.pack(side=RIGHT, padx=10)

        self.slider = ct.CTkSlider(self.slide_time_frame, height=20, fg_color="#4b5d4b", progress_color="#106A43", bg_color="transparent", 
                                   command=lambda event: self.slide_song(), from_=0, to=100)
        self.slider.pack(fill=X, padx=20)
        self.slider.set(0)

        self.slide_time_frame.pack(side=TOP, fill=X)

        self.singer_name = ct.CTkLabel(self.control_frame, text="Singer name", font=("IBM Plex Sans", 20, "bold"), text_color="#a5a5a5")
        self.singer_name.pack(side=LEFT, padx=10)

        self.play_control_frame = ct.CTkFrame(self.control_frame, fg_color="transparent", width=0)

        self.skip_backward = ct.CTkButton(self.play_control_frame, text="", image=self.skip_backward_img, width=0, fg_color="transparent", corner_radius=5, bg_color="transparent", command=self.backward_song)
        self.skip_backward.pack(side=LEFT)

        self.pause = ct.CTkButton(self.play_control_frame, text="", image=self.stop_img, width=0, fg_color="transparent", corner_radius=5, bg_color="transparent", command=self.pauseStreaming, state="disabled")
        self.pause.pack(side=LEFT, padx=15)
        self.skip_forward = ct.CTkButton(self.play_control_frame, text="", image=self.skip_forward_img, width=0, fg_color="transparent", corner_radius=5, bg_color="transparent", command=self.forward_song)
        self.skip_forward.pack(side=LEFT)

        self.sound_control_frame = ct.CTkFrame(self.control_frame, fg_color="transparent", width=0)
        self.volume_image__ = ct.CTkLabel(self.sound_control_frame, text="", image=self.volume_img, width=0, fg_color="transparent", corner_radius=5)
        self.volume_image__.pack(side=LEFT)
        self.volume_main_slider = ct.CTkSlider(self.sound_control_frame, from_=0, to=100, number_of_steps=100, height=20, progress_color="#1ED765",
                                                button_color="#1ED765", button_hover_color="#17b856", command=self.on_volume_change__)
        self.volume_main_slider.set(AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        self.volume_tooltip = CTkToolTip(self.volume_main_slider, message="", font=("IBM Plex Sans", 15), text_color="white", delay=0, always_on_top=True)
        self.volume_main_slider.pack(side=LEFT, padx=10)

        self.pcf_padx = 200
        
        self.play_control_frame.pack(side=LEFT, fill=X, expand=True, padx=self.pcf_padx)
        self.sound_control_frame.pack(side=LEFT, fill=X, expand=True, padx=10)

        self.control_frame.pack(side=BOTTOM, fill=X, pady=10)

        self.trends_frame = ct.CTkFrame(self.popular_frame, fg_color="#241d48", bg_color="#241d48")

        ct.CTkLabel(self.trends_frame, text="Popular ", font=("IBM Plex Sans", 40, "bold")).pack(side=TOP, anchor="nw", padx=35, pady=20)
        
        self.trending_song_frame = ct.CTkFrame(self.trends_frame, fg_color="transparent")
        trending_songs = self.generate_random_song(10)

        for i, trends in enumerate(trending_songs):
            i+=1
            ct.CTkButton(self.trending_song_frame, text=f"{i}. {trends}", font=("Poppins", 21, "normal"), 
                         anchor="w", corner_radius=10, fg_color="#3d375a", hover_color="#464d75", command=lambda song=trends: self.streamMusic(f"{song}.mp3")).pack(side=TOP, fill=X, ipady=10, padx=10, pady=5)

        self.trending_song_frame.pack(side=TOP, fill=X, padx=20, pady=10)
        
        self.trends_frame.pack(fill=BOTH, expand=True)

        self.all_songs = []
        self.previous_song = []

        # Focus the home tab first
        self.select_frame_name("home")
        self.position = 0
        self.loop = False
        self.music_scale = False
        
        intital_songs = self.generate_random_song(10)
        for item in intital_songs:
            ct.CTkButton(self.searching_frame, text=f" {item}", width=20, font=("Poppins", 21, "normal"), command=lambda item=item: self.on_button_click(item), 
                        anchor="w", corner_radius=0, fg_color="#333", text_color="#c7c3c3", image=self.rise_img2, hover_color="#444").pack(fill=X, pady=0, ipady=10, padx=5)

        self.user_dragging = False
        self.slider.bind("<ButtonPress-1>", lambda e: setattr(self, "user_dragging", True))
        self.slider.bind("<ButtonRelease-1>", lambda e: setattr(self, "user_dragging", False))

        self.audio = AudioStream()
        self.start_music_loading()
        self._poll_startup_queue()
        self._poll_play_queue()
        self.central_update()

        try:
            current = AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar() * 100
            self.volume_slider.set(current)
            self.volume_value_label.configure(text=f"{int(current)}%")
        except:
            self.volume_slider.set(80)

    def on_volume_change__(self, value):
        try:
            vol = float(value)
            self.volume_tooltip.configure(message=f"{int(vol)}%")
            if vol == 0:
                self.volume_image__.configure(image=self.volume_mute_img, text="")
            if vol > 0:
                self.volume_image__.configure(image=self.volume_img, text="")

            # Correct modern way
            device = AudioUtilities.GetSpeakers()
            device.EndpointVolume.SetMasterVolumeLevelScalar(vol / 100, None)

        except Exception as e:
            print("Volume Error →", e)


    def on_volume_change(self, value):
        try:
            vol = float(value)
            self.volume_value_label.configure(text=f"{int(vol)}%")

            # Correct modern way
            device = AudioUtilities.GetSpeakers()
            device.EndpointVolume.SetMasterVolumeLevelScalar(vol / 100, None)

        except Exception as e:
            print("Volume Error →", e)

    def _get_song_data(self):
        if self._song_data_cache is None:
            self._song_data_cache = get_song_data()
        return self._song_data_cache

    def central_update(self):
        """One lightweight UI refresh loop; never downloads images repeatedly."""
        try:
            if self.audio:
                duration_ms = self.audio.get_duration()
                current_ms = self.audio.get_current_time()

                self.time_elapsed_label.configure(text=self.audio.format_time(current_ms))
                self.music_duration_label.configure(text=self.audio.format_time(duration_ms))

                if duration_ms > 0 and not self.user_dragging:
                    progress = (current_ms / duration_ms) * 100
                    self.slider.set(max(0, min(progress, 100)))

        except Exception as error:
            print("central_update error:", error)

        self._central_after = self.root.after(300, self.central_update)

    def _load_favourite_header_once(self, image_name):
        pass

    def start_music_loading(self):
        if self._loading_music or self._music_loaded:
            return

        self._loading_music = True
        threading.Thread(target=self._music_data_worker, daemon=True).start()

    def _music_data_worker(self):
        try:
            data = get_music_data()
            self._startup_queue.put(("music_data", data))
        except Exception as error:
            self._startup_queue.put(("error", f"Music data error: {error}"))

    def _artists_data_worker(self):
        try:
            data = get_singer_data()
            self._startup_queue.put(("artists_data", data))
        except Exception as error:
            self._startup_queue.put(("error", f"Artist data error: {error}"))

    def _poll_startup_queue(self):
        try:
            while True:
                kind, payload = self._startup_queue.get_nowait()

                if kind == "music_data":
                    self._pending_music = list(payload)
                    self._build_music_batch()

                elif kind == "artists_data":
                    self.artists_data = list(payload)
                    self._build_artist_batch()

                elif kind == "error":
                    print(payload)

        except queue.Empty:
            pass

        self._startup_after = self.root.after(40, self._poll_startup_queue)

    def _build_music_batch(self, batch_size=2):
        """Create only a few song cards per GUI cycle."""
        if not getattr(self, "_pending_music", None):
            self._loading_music = False
            self._music_loaded = True
            return

        for _ in range(min(batch_size, len(self._pending_music))):
            song = self._pending_music.pop(0)
            self.add_Music(
                music_name=song["name"],
                music_image_name=song["image"],
                tab=song["tab"]
            )

        self.root.after(1, self._build_music_batch)

    def start_artist_loading(self):
        if self._artists_loaded or self._artists_loading:
            return

        self._artists_loading = True
        self.artist_loading_label.configure(text="Loading artists...")
        threading.Thread(target=self._artists_data_worker, daemon=True).start()

    def _build_artist_batch(self, batch_size=1):
        if not hasattr(self, "_pending_artists"):
            self._pending_artists = list(self.artists_data)
            self._artist_row_frame = None
            self._artist_index = 0
            self.artist_loading_label.pack_forget()
            self.artist_frame.pack(side=TOP, fill=BOTH, expand=True, padx=20, pady=40)

        if not self._pending_artists:
            if self._artist_row_frame:
                self._artist_row_frame.pack(fill=X, side=TOP, pady=20)
            self._artists_loading = False
            self._artists_loaded = True
            del self._pending_artists
            return

        for _ in range(min(batch_size, len(self._pending_artists))):
            artist = self._pending_artists.pop(0)

            if self._artist_index % 4 == 0:
                if self._artist_row_frame:
                    self._artist_row_frame.pack(fill=X, side=TOP, pady=20)
                self._artist_row_frame = ct.CTkFrame(self.artist_frame, fg_color="transparent")

            name = artist["file"]
            image = GitHubImageLoader(
                f"https://raw.githubusercontent.com/SarthakTools/music/main/singersImage/{name}"
            ).fetch_image(250, 250)

            label = ct.CTkLabel(
                self._artist_row_frame,
                text=artist["name"],
                font=("IBM Plex Sans", 20, "bold"),
                image=image,
                compound=TOP,
                text_color="white"
            )
            label.pack(side=LEFT, padx=25)
            self._artist_index += 1

        self.root.after(1, self._build_artist_batch)

    def forward_song(self):
        self._seek_by_seconds(10)

    def backward_song(self):
        self._seek_by_seconds(-10)

    def _seek_by_seconds(self, seconds: int):
        try:
            current_ms = self.audio.get_current_time()
            if current_ms < 0:
                current_ms = 0

            seek_ms = current_ms + (seconds * 1000)

            if seek_ms < 0:
                seek_ms = 0

            duration = self.audio.get_duration()
            if duration > 0 and seek_ms > duration:
                seek_ms = duration - 1000

            self.audio.seek(seek_ms)
            self.update_progress()
        except Exception as e:
            print(f"Seek error: {e}")       

    def create_artist_grid(self):
        row_frame = None
        for i, artist in enumerate(self.artists_data):
            name = artist["file"]
            self.loader = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/singersImage/{name}")
            if i % 4 == 0: 
                if row_frame:
                    row_frame.pack(fill=X, side=TOP, pady=20)
                row_frame = ct.CTkFrame(self.artist_frame, fg_color="transparent")
            ctk_image = self.loader.fetch_image(width=250, height=250)

            artist_label = ct.CTkLabel(
                row_frame,
                text=artist["name"],
                font=("IBM Plex Sans", 20, "bold"),
                image=ctk_image,
                compound=TOP,
                text_color="white"
            )
            artist_label.pack(side=LEFT, padx=25)
        if row_frame:
            row_frame.pack(fill=X, side=TOP, pady=20)

        self.artist_frame.pack(side=TOP, fill=BOTH, expand=True, padx=20, pady=40)

    def changeProfilePhoto(self):
        pass

    def deleteAccount(self):
        if os.path.exists("C:\\cookies\\user-name.txt"):
            msg = CTkMessagebox(title="Delete Account", message=" Are you sure to delete account ? Restart the program to create new account.", icon="question", font=("monospace", 15, "bold"), text_color="white", wraplength=550, option_1="Cancel", option_2="No", option_3="Yes", width=550) 
            if msg.get() == "Yes":
                    shutil.rmtree("C:\\cookies")
                    self.root.destroy()
            else:
                pass

    def cleanup(self):
        filename = ["avatar_name.txt", "password.txt", "user-name.txt"]
        for files in filename:
            os.remove(f"C:\\cookies\\{files}")
        try:
            self.audio.stop()
        except:
            pass

        pending_tasks = self.root.tk.call('after', 'info')
        for task_id in pending_tasks:
            self.root.after_cancel(task_id)

        self.root.destroy()

    def generate_random_song(self, number):
        return random.sample(self.all_songs_name, number)

    def search_filter(self, search_term):
        for widget in self.searching_frame.winfo_children():
            widget.destroy()

        if search_term == "":
            initial_fruits = self.generate_random_song(8)
            for item in initial_fruits:
                ct.CTkButton(self.searching_frame, text=f" {item}", width=20, font=("Poppins", 21, "normal"), command=lambda item=item: self.on_button_click(item), 
                        anchor="w", corner_radius=0, fg_color="#333", text_color="#c7c3c3", image=self.rise_img2, hover_color="#444").pack(fill=X, pady=0, ipady=10, padx=5)
        else:
            filtered_data = [item for item in self.all_songs_name if item.lower().startswith(search_term.lower())]
            filtered_data.sort()
            for item in filtered_data:
                ct.CTkButton(self.searching_frame, text=f" {item}", width=20, font=("Poppins", 21, "normal"), command=lambda item=item: self.on_button_click(item), 
                        anchor="w", corner_radius=0, fg_color="#333", text_color="#c7c3c3", image=self.rise_img2, hover_color="#444").pack(fill=X, pady=0, ipady=10, padx=5)

    def on_button_click(self, item):
        music_name = f"{item}.mp3"
        self.streamMusic(music_name)

    def on_button_release(self, event):
        search_term = event.widget.get()
        self.search_filter(search_term)

    def show_password(self):
        self.icon_eyes.configure(image=self.eyes_icon_open, command=self.hide_password)
        self.password_input.configure(text=self.password)

    def hide_password(self):
        self.icon_eyes.configure(image=self.eyes_icon_closed, command=self.show_password)
        self.password_input.configure(text="********")
        
    def toggle_update(self, event):
        self.update_btn.toggle()

    def playPlaylist_song(self):        
        pass

    def update_current_song_name(self):
        pass

    def update_current_song_ui(self):
        pass

    def start_playlist_monitor(self):
        pass

    def open_favourites(self):
        pass

    def update_current_song(self):
        pass

    def update_songs_(self):
        pass
        
    def updateFavouritePlaylistImage(self):
        pass

    def loop_song(self):
        pass

    def add_favourite(self):
        pass

    def remove_favourite(self):
        pass

    def slide_song(self, value=None):
        duration = self.audio.get_duration()
        if duration <= 0:
            return

        seek_ms = int((self.slider.get() / 100) * duration)
        self.audio.seek(seek_ms)

    def add_Music(self, music_name, music_image_name, tab="home"):
        self.all_songs.append(music_name)
        # global song_img
        music_image_path = music_image_name.lower()
        song_img = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/{music_image_path}").fetch_image(280, 230)

        if tab not in self.frames:
            self.frames[tab] = ct.CTkFrame(self.home_frame, fg_color=self.color_home_frame)

        song_button = ct.CTkButton(self.frames[tab], text=music_name, fg_color=self.color_home_frame, bg_color="transparent", corner_radius=10,
                                   image=song_img, command=lambda: self.streamMusic(f"{music_name}.mp3"), compound=TOP, font=("IBM Plex Sans", 20))
        song_button.pack(side=LEFT, ipady=10, ipadx=0)
        self.frames[tab].pack(side=TOP, fill=X, pady=2)
    
    def streamMusic(self, song_name):
        """Play a song without freezing the GUI."""
        raw_musicName = song_name

        # Already playing this exact track?
        if self.music_playing == song_name and not self._is_loading_song:
            return

        # Cancel any previous in-flight load
        self._current_play_id += 1
        play_id = self._current_play_id
        self._is_loading_song = True

        # Immediate UI feedback
        self.singer_name.configure(text="Loading...")
        self.pause.configure(state="disabled")
        try:
            self.audio.stop()
        except Exception:
            pass

        def worker():
            try:
                # Build URL (same logic you already had)
                name_parts = song_name.split(" ")
                encoded = "%20".join(name_parts) if len(name_parts) > 1 else "".join(name_parts)
                url = f"https://raw.githubusercontent.com/SarthakTools/music/main/songs/{encoded}"

                # Create player + load (this is the slow part)
                audio = AudioStream()
                audio.load_single(url)

                # Cover image (also slow)
                img_name = (
                    raw_musicName.lower()
                    .replace(" ", "_")
                    .replace("%20", "_")
                    .rsplit(".", 1)[0] + ".png"
                )
                cover = GitHubImageLoader(
                    f"https://raw.githubusercontent.com/SarthakTools/music/main/{img_name}"
                ).fetch_image(45, 45)

                artist_dict = self._get_song_data()
                key = raw_musicName.split(".")[0]
                artist = artist_dict.get(key, "Unknown Artist")

                # Send everything back to the main thread
                self._play_queue.put({
                    "play_id": play_id,
                    "audio": audio,
                    "cover": cover,
                    "artist": artist,
                    "raw": raw_musicName,
                    "encoded": encoded,
                    "error": None,
                })
            except Exception as e:
                self._play_queue.put({
                    "play_id": play_id,
                    "error": str(e),
                })

        threading.Thread(target=worker, daemon=True).start()

    def _poll_play_queue(self):
        try:
            while True:
                result = self._play_queue.get_nowait()

                # Ignore stale clicks
                if result.get("play_id") != self._current_play_id:
                    continue

                self._is_loading_song = False

                if result.get("error"):
                    print("Play error:", result["error"])
                    self.singer_name.configure(text="Error loading song")
                    continue

                # Clean up previous player
                try:
                    self.audio.stop()
                    if hasattr(self.audio, "cleanup"):
                        self.audio.cleanup()
                except Exception:
                    pass

                # Switch to the new player
                self.audio = result["audio"]
                self.audio.play()

                self.music_playing = result["encoded"]
                self.previous_song.append(result["raw"])

                # Update UI
                self.image_song_label.configure(image=result["cover"])
                self.image_song_label.image = result["cover"]   # keep reference
                self.singer_name.configure(text=result["artist"])
                self.pause.configure(state="normal", image=self.pause_img, command=self.pauseStreaming)
                self.slider.set(0)

                # Optional: keep the same padding logic you had
                if len(result["artist"]) > 16:
                    self.play_control_frame.pack_configure(padx=self.pcf_padx)
                else:
                    self.play_control_frame.pack_configure(padx=self.pcf_padx)

        except queue.Empty:
            pass

        self.root.after(50, self._poll_play_queue)

    def pauseStreaming(self):
        self.audio.pause()
        self.pause.configure(image=self.stop_img, command=self.resumeStreaming)

    def resumeStreaming(self):
        self.audio.resume()
        self.pause.configure(image=self.pause_img, command=self.pauseStreaming)

    def configure_music(self, music_name):
        pass

    def insertSongImage(self, image):
        global song_image_path, music_name
        music_name = image.lower().replace(" ", "_")
        music_name = music_name.split(".")
        music_name[1] = ".png"
        music_name = str(music_name[0] + music_name[1])
        music_name = music_name.replace("%20", "_")

        self.image = GitHubImageLoader(f"https://raw.githubusercontent.com/SarthakTools/music/main/{music_name}").fetch_image(45, 45)
        self.image_song_label.configure(image=self.image)

    def update_progress(self):
        pass

    def select_frame_name(self, name):
        if name == "artists":
            self.start_artist_loading()

        self.search.configure(fg_color="#444" if name == "search" else "transparent")
        self.home.configure(fg_color="#444" if name == "home" else "transparent")
        self.artists.configure(fg_color="#444" if name == "artists" else "transparent")
        self.trending.configure(fg_color="#444" if name == "trending" else "transparent")
        self.settings.configure(fg_color="#444" if name == "settings" else "transparent")
        # self.favourites_btn.configure(fg_color="#444" if name == "favourites" else "transparent")

        if name == "search":
            self.search_frame.pack(fill=BOTH, expand=True)
        else:
            self.search_frame.pack_forget()
        if name == "home":
            self.home_frame.pack(fill=BOTH, expand=True)
        else:
            self.home_frame.pack_forget()
        if name == "artists":
            self.discover_frame.pack(fill=BOTH, expand=True)
        else:
            self.discover_frame.pack_forget()
        if name == "trending":
            self.popular_frame.pack(fill=BOTH, expand=True)
        else:
            self.popular_frame.pack_forget()
        # if name == "favourites":
        #     self.favourites_frame.pack(fill=BOTH, expand=True)
        # else:
        #     self.favourites_frame.pack_forget()
        if name == "settings":
            self.settings_frame.pack(fill=BOTH, expand=True)
        else:
            self.settings_frame.pack_forget()

    def show_music(self):
        """Compatibility wrapper for older calls."""
        self.start_music_loading()

if __name__ == "__main__":
    root = ct.CTk()
    root.geometry("1000x600+200+40")
    root.resizable(False, False)

    base_folder = "C:\\cookies"

    if os.path.isdir(base_folder): 
        filename = ["avatar_name.txt", "password.txt", "user-name.txt"]
        all_files_exist = os.path.isdir(base_folder) and all(os.path.exists(os.path.join(base_folder, file)) for file in filename)
        if all_files_exist:
            app = PyMusic(root)
        else:
            PyMusicInstaller(root)
    else:
        PyMusicInstaller(root)
        # IntroPage(root)

    root.mainloop()