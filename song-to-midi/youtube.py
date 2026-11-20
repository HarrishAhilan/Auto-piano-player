"""YouTube link -> audio file (for personal use: playing songs on your own piano).

Only single YouTube videos are accepted (no playlists, no other sites), up to 15 minutes.
Uses yt-dlp to fetch the best audio stream and the bundled ffmpeg (imageio-ffmpeg) to turn it into WAV.
"""
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_SECONDS = 15 * 60
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}


def video_id(url):
    """The 11-character video id, or None if this isn't a single YouTube video link."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or u.hostname not in HOSTS:
        return None
    if u.hostname.endswith("youtu.be"):
        vid = u.path.lstrip("/").split("/")[0]
    elif u.path == "/watch":
        vid = parse_qs(u.query).get("v", [""])[0]
    else:
        m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", u.path)
        vid = m.group(2) if m else ""
    return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or "") else None


def safe_name(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip(" .")
    name = re.sub(r"\s*[\(\[](official|lyrics?|audio|video|hd|hq|4k|remaster(ed)?)[^\)\]]*[\)\]]", "", name, flags=re.I).strip()
    return name[:100] or "YouTube song"


def download(url, status=print, progress=None):
    """Returns (wav_path, title, seconds). Raises ValueError with a friendly message on problems."""
    import imageio_ffmpeg
    import yt_dlp
    vid = video_id(url)
    if not vid:
        raise ValueError("That doesn't look like a YouTube video link (e.g. https://www.youtube.com/watch?v=...).")
    clean = f"https://www.youtube.com/watch?v={vid}"
    status("Looking up the YouTube video...")
    opts = dict(quiet=True, no_warnings=True, noplaylist=True, skip_download=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(clean, download=False)
        except Exception as e:
            raise ValueError(f"YouTube wouldn't give the video ({str(e).splitlines()[0][:160]}).")
    title, secs = info.get("title") or "YouTube song", info.get("duration") or 0
    if info.get("is_live"):
        raise ValueError("That's a live stream - pick a normal video.")
    if secs > MAX_SECONDS:
        raise ValueError(f"That video is {secs // 60} minutes long - the limit is {MAX_SECONDS // 60}.")
    tmp = Path(tempfile.mkdtemp(prefix="yt-"))

    def hook(d):
        if progress and d.get("status") == "downloading" and d.get("total_bytes"):
            progress(d["downloaded_bytes"] / d["total_bytes"])
    status(f"Downloading the audio of \"{title}\"...")
    dl = dict(quiet=True, no_warnings=True, noplaylist=True, format="bestaudio/best",
              outtmpl=str(tmp / "audio.%(ext)s"), progress_hooks=[hook])
    with yt_dlp.YoutubeDL(dl) as ydl:
        ydl.download([clean])
    src = next((p for p in tmp.iterdir() if p.name.startswith("audio.")), None)
    if src is None:
        raise ValueError("The download didn't produce an audio file.")
    wav = tmp / "audio.wav"
    status("Preparing the audio...")
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src),
                        "-vn", "-ac", "2", "-ar", "44100", str(wav)], capture_output=True, text=True)
    src.unlink(missing_ok=True)
    if r.returncode != 0 or not wav.exists():
        raise ValueError(f"Couldn't decode the audio ({r.stderr.strip()[:160]}).")
    return wav, safe_name(title), secs
