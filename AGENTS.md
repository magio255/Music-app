# Music-app (magiomusic player)

PySide6 + pygame desktop music player. Main file: `video player/video_prehravac.py`. Code and UI strings are in Czech.

## Build / run

```
pip install PySide6 pygame mutagen
python "video player/video_prehravac.py"
```

## Headless testing (this sandbox has no display and no sound card)

```
cd "video player"
SDL_AUDIODRIVER=dummy QT_QPA_PLATFORM=offscreen python -u <test>.py
```

Qt needs `libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libdbus-1-3 libfontconfig1`.
Use `app.processEvents()` instead of `QTimer.singleShot` + `app.exec()` — the event loop hangs in this environment.
Generate test audio with `imageio_ffmpeg` (`ffmpeg -f lavfi -i "sine=frequency=440:duration=30"`).
Always delete test MP3/LRC files and `__pycache__` afterwards, and `git checkout -- "video player/playlists.json"`.

## Always deliver a zip

After every change, build a fresh zip the user can download:

```
python - <<'PY'
import zipfile
from pathlib import Path
root = Path("/workspace/project"); out = Path("/workspace/downloads/magiomusic-prehravac.zip")
out.parent.mkdir(parents=True, exist_ok=True)
if out.exists(): out.unlink()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in {"__pycache__", ".git"} for part in rel.parts): continue
        if p.suffix == ".pyc": continue
        if p.is_file(): z.write(p, rel.as_posix())
print(out, out.stat().st_size)
PY
```

Then serve it so it is reachable from outside:

```
cd /workspace/downloads && nohup python -m http.server 12000 --bind 0.0.0.0 > /tmp/httpd.log 2>&1 &
```

Download link: `https://work-1-lthsidmwbdrecgwk.prod-runtime.all-hands.dev/magiomusic-prehravac.zip`
(port 12001 / work-2 is not routed to the HTTP server). Verify with `curl -sI` and check the size.
