#!/usr/bin/env python3
"""
WAVEMAKRZ — demucs_runner.py
Real AI stem separation using Demucs — CPU compatible, no GPU required.
Neutralises torchcodec completely using a safe stub that allows all attribute
access but raises ImportError only if code tries to actually CALL/instantiate
a torchcodec class.

Usage: python demucs_runner.py <input_file> <output_dir> [model]
Output: JSON + WAV stems in <output_dir>
"""

# ══════════════════════════════════════════════════════════════════════════════
#  CRITICAL — must happen BEFORE any other imports.
#  Install a safe torchcodec stub so torchaudio and Demucs can probe the
#  module without crashing, but cannot actually load audio through torchcodec.
# ══════════════════════════════════════════════════════════════════════════════
import os
import sys
import types


def _install_torchcodec_stub():
    """
    Replace (or pre-empt) torchcodec with a minimal safe stub.

    Design contract
    ───────────────
    • import torchcodec                            → succeeds, returns stub
    • torchcodec.__file__                          → plain string  (no recursion)
    • torchcodec.__path__                          → []            (no submodule loading)
    • torchcodec.__version__                       → "0.0.0"
    • torchcodec.decoders                          → _NeverCallable (falsy)
    • hasattr(torchcodec, "anything")              → True          (no AttributeError)
    • bool(torchcodec.decoders)                    → False         (Demucs sees it disabled)
    • from torchcodec.decoders import AudioDecoder → succeeds, gives _NeverCallable
    • AudioDecoder(path)        [calling it]       → ImportError   (actual use blocked)
    """

    # ── _NeverCallable ────────────────────────────────────────────────────────
    # Returned for every attribute that isn't a known dunder.
    # Safe to access, bool-falsy, raises only when called.

    class _NeverCallable:
        __slots__ = ("_n",)

        def __init__(self, name: str = "torchcodec.?"):
            object.__setattr__(self, "_n", name)

        # Callable → raises ImportError (the actual guard)
        def __call__(self, *args, **kwargs):
            raise ImportError(
                f"{object.__getattribute__(self, '_n')} is not available: "
                "torchcodec is not installed. "
                "WAVEMAKRZ uses soundfile / ffmpeg / librosa for audio loading."
            )

        # Safe chained attribute access:  tc.decoders.AudioDecoder.something
        def __getattr__(self, attr: str) -> "_NeverCallable":
            return _NeverCallable(f"{object.__getattribute__(self, '_n')}.{attr}")

        # Falsy → Demucs `if torchcodec.decoders:` guards evaluate as disabled
        def __bool__(self) -> bool:
            return False

        def __repr__(self) -> str:
            return f"<torchcodec stub [{object.__getattribute__(self, '_n')}]>"

        # Iteration / containment — just raise, nothing to iterate
        def __iter__(self):
            raise TypeError(f"{object.__getattribute__(self, '_n')} is a stub")

    # ── _StubModule ───────────────────────────────────────────────────────────
    # A real ModuleType subclass so isinstance(stub, types.ModuleType) is True.
    # All dunder attrs that Python's import machinery needs are set as real
    # values; everything else goes through __getattr__ → _NeverCallable.

    _STUB_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_torchcodec_stub_marker"
    )

    class _StubModule(types.ModuleType):
        # __getattr__ is called only for attrs NOT in __dict__
        def __getattr__(self, attr: str):
            return _NeverCallable(f"{self.__name__}.{attr}")

    def _make_stub(name: str) -> _StubModule:
        stub = _StubModule(name)
        # Set all attrs that Python / importlib access on a normal module
        stub.__name__     = name
        stub.__package__  = name.split(".")[0]
        stub.__file__     = _STUB_FILE      # must be a plain string
        stub.__path__     = []              # empty → no submodule filesystem scan
        stub.__spec__     = None            # signals "stub / not a real package"
        stub.__loader__   = None
        stub.__version__  = "0.0.0"
        stub.__doc__      = f"torchcodec stub installed by WAVEMAKRZ ({name})"
        return stub

    # Register stub for every known torchcodec sub-namespace
    _STUB_NAMES = [
        "torchcodec",
        "torchcodec.decoders",
        "torchcodec.decoders._core",
        "torchcodec._core",
        "torchcodec.models",
        "torchcodec.datasets",
        "torchcodec.utils",
    ]
    for _name in _STUB_NAMES:
        if _name not in sys.modules:
            sys.modules[_name] = _make_stub(_name)

    # Tell torchaudio NOT to use the new backend dispatcher (works on 2.x)
    os.environ["TORCHAUDIO_USE_BACKEND_DISPATCHER"] = "0"
    os.environ.setdefault("TORCHAUDIO_BACKEND", "soundfile")


# ── Run immediately, before any other import ──────────────────────────────────
_install_torchcodec_stub()


# ══════════════════════════════════════════════════════════════════════════════
#  Normal imports (safe now — stub is in place)
# ══════════════════════════════════════════════════════════════════════════════
import json
import shutil
import subprocess
import threading
import time
import warnings

warnings.filterwarnings("ignore")


# ─── LOGGING ──────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[Demucs] {msg}", flush=True)


def prog(pct: float, msg: str = "") -> None:
    print(f"PROGRESS:{pct:.1f} {msg}", flush=True)


# ─── FIND FFMPEG ──────────────────────────────────────────────────────────────
def find_ffmpeg() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in [
        "../bin/ffmpeg.exe", "../bin/ffmpeg",
        "../../bin/ffmpeg.exe", "../../bin/ffmpeg",
    ]:
        candidate = os.path.normpath(os.path.join(script_dir, rel))
        if os.path.exists(candidate):
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except ImportError:
        pass
    return "ffmpeg"


# ─── PRE-CONVERT TO 44.1 kHz WAV ─────────────────────────────────────────────
def to_wav_44100(src: str, dst: str) -> str:
    ffmpeg = find_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-y", "-i", src,
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", dst],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg pre-conversion failed: {result.stderr.decode()[:300]}"
        )
    return dst


# ─── PATCH torchaudio.load ────────────────────────────────────────────────────
def _patch_torchaudio_load() -> None:
    """
    Wrap torchaudio.load so it always tries soundfile/ffmpeg backends first,
    never reaching the torchcodec dispatcher path.
    Idempotent — safe to call multiple times.
    """
    try:
        import torchaudio
    except ImportError:
        return  # torchaudio not installed; safe_load_audio will fall through

    if getattr(torchaudio, "_wavemakrz_patched", False):
        return

    _orig = torchaudio.load

    def _safe_load(path, *args, **kwargs):
        # Strip any backend kwarg that might point at torchcodec
        kwargs.pop("backend", None)

        for backend in ("soundfile", "ffmpeg", "sox_io"):
            try:
                return _orig(path, *args, backend=backend, **kwargs)
            except TypeError:
                # Old torchaudio: no `backend` kwarg → break and use legacy path
                break
            except RuntimeError as exc:
                low = str(exc).lower()
                if "torchcodec" in low or "torchcodec" in low:
                    continue   # skip, try next backend
                raise          # real error

        # Legacy torchaudio (<2.1): set global backend then call without kwarg
        for backend in ("soundfile", "ffmpeg", "sox_io"):
            try:
                torchaudio.set_audio_backend(backend)
                return _orig(path, *args, **kwargs)
            except Exception:
                continue

        return _orig(path, *args, **kwargs)   # last resort, may raise

    torchaudio.load = _safe_load
    torchaudio._wavemakrz_patched = True
    log("torchaudio.load patched — soundfile/ffmpeg backend priority")


# ─── SAFE AUDIO LOADER ────────────────────────────────────────────────────────
def safe_load_audio(filepath: str, sr: int = 44100):
    """
    Load audio to float32 numpy array shape (channels, samples).
    Priority: torchaudio → librosa → ffmpeg-pipe.
    Never uses torchcodec.
    Returns: (numpy_array, sample_rate)
    """
    import numpy as np
    filepath = str(filepath)
    errors: dict = {}

    # 1. torchaudio (patched)
    try:
        import torchaudio
        _patch_torchaudio_load()

        waveform, orig_sr = torchaudio.load(filepath)
        audio = waveform.numpy().astype(np.float32)
        if orig_sr != sr:
            import torchaudio.functional as F_ta
            import torch
            audio = F_ta.resample(
                torch.from_numpy(audio), orig_sr, sr
            ).numpy().astype(np.float32)
        if audio.ndim == 1:
            audio = np.stack([audio, audio])
        elif audio.shape[0] == 1:
            audio = np.vstack([audio, audio])
        log(f"Loaded via torchaudio: shape={audio.shape} sr={sr}")
        return audio, sr

    except Exception as exc:
        errors["torchaudio"] = str(exc)
        log(f"torchaudio load failed ({exc}) — trying librosa")

    # 2. librosa
    try:
        import librosa
        y, orig_sr = librosa.load(filepath, sr=sr, mono=False)
        if y.ndim == 1:
            y = np.stack([y, y])
        elif y.shape[0] == 1:
            y = np.vstack([y, y])
        audio = y.astype(np.float32)
        log(f"Loaded via librosa: shape={audio.shape} sr={sr}")
        return audio, sr

    except Exception as exc:
        errors["librosa"] = str(exc)
        log(f"librosa load failed ({exc}) — trying ffmpeg pipe")

    # 3. raw ffmpeg pipe (always works)
    try:
        ff = find_ffmpeg()
        cmd = [
            ff, "-i", filepath,
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ar", str(sr), "-ac", "2",
            "-", "-hide_banner", "-loglevel", "error",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[:300])
        raw = np.frombuffer(proc.stdout, dtype=np.float32).copy()
        if len(raw) % 2 == 0:
            audio = raw.reshape(-1, 2).T.astype(np.float32)
        else:
            audio = np.stack([raw, raw]).astype(np.float32)
        log(f"Loaded via ffmpeg-pipe: shape={audio.shape} sr={sr}")
        return audio, sr

    except Exception as exc:
        errors["ffmpeg_pipe"] = str(exc)

    raise RuntimeError(
        "All audio loading methods failed:\n" +
        "\n".join(f"  {k}: {v}" for k, v in errors.items())
    )


# ─── DEMUCS VIA PYTHON API ────────────────────────────────────────────────────
def run_demucs_api(input_wav: str, output_dir: str, model_name: str,
                   on_progress=None) -> dict:
    import torch
    import numpy as np
    import soundfile as sf
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from demucs.audio import convert_audio

    log(f"Loading model: {model_name}")
    if on_progress:
        on_progress(20, f"Loading model {model_name} (first run ~80-200 MB download)…")

    try:
        model = get_model(model_name)
    except Exception as exc:
        if model_name != "htdemucs":
            log(f"Model {model_name} unavailable ({exc}), falling back to htdemucs")
            model = get_model("htdemucs")
        else:
            raise

    model.eval()
    model.cpu()
    # Use all available CPU cores for torch operations
    cpu_count = os.cpu_count() or 2
    torch.set_num_threads(cpu_count)
    torch.set_num_interop_threads(max(2, cpu_count // 2))
    log(f"Model ready — sources={model.sources} sr={model.samplerate} | CPU threads={cpu_count}")
    if on_progress:
        on_progress(30, "Model ready — loading audio…")

    audio_np, _ = safe_load_audio(input_wav, sr=model.samplerate)
    audio_t = torch.from_numpy(audio_np)
    audio_t = convert_audio(audio_t, model.samplerate,
                             model.samplerate, model.audio_channels)
    audio_t = audio_t.unsqueeze(0)           # (1, channels, samples)
    log(f"Input tensor: {audio_t.shape}")

    if on_progress:
        on_progress(38, "Running AI separation on CPU…")

    result_ref: list = [None]
    error_ref:  list = [None]

    def _separate():
        try:
            with torch.no_grad():
                result_ref[0] = apply_model(
                    model, audio_t,
                    device="cpu", progress=False, num_workers=2,
                    segment=getattr(model, "segment", None),
                )
        except Exception as exc:
            error_ref[0] = exc

    thread = threading.Thread(target=_separate, daemon=True)
    thread.start()

    pct = 38
    while thread.is_alive():
        time.sleep(3)
        if pct < 88:
            pct += 2
        if on_progress:
            on_progress(pct, "Separating stems with Demucs AI…")

    thread.join()
    if error_ref[0] is not None:
        raise error_ref[0]

    if on_progress:
        on_progress(90, "Saving stems…")

    os.makedirs(output_dir, exist_ok=True)
    stems: dict = {}
    sources_out = result_ref[0]             # (1, n_sources, channels, samples)

    for idx, name in enumerate(model.sources):
        stem = sources_out[0, idx].cpu().numpy().T    # (samples, channels)
        peak = float(abs(stem).max())
        if peak > 0.89:
            stem = stem * (0.89 / peak)
        stem = stem.clip(-1.0, 1.0)
        out_path = os.path.join(output_dir, f"{name}.wav")
        sf.write(out_path, stem, model.samplerate, subtype="PCM_24")
        stems[name] = out_path
        log(f"Stem saved: {name}.wav  ({stem.shape[0] / model.samplerate:.1f}s)")

    return stems


# ─── SUBPROCESS FALLBACK ──────────────────────────────────────────────────────
def run_demucs_subprocess(input_wav: str, output_dir: str, model_name: str,
                          on_progress=None) -> dict:
    temp_out = os.path.join(output_dir, "_demucs_tmp")
    shutil.rmtree(temp_out, ignore_errors=True)
    os.makedirs(temp_out, exist_ok=True)

    env = {**os.environ,
           "TORCHAUDIO_USE_BACKEND_DISPATCHER": "0",
           "TORCHAUDIO_BACKEND": "soundfile",
           "PYTHONDONTWRITEBYTECODE": "1"}

    cmd = [sys.executable, "-m", "demucs",
           "--out", temp_out, "--name", model_name,
           "--device", "cpu", "--jobs", "1", input_wav]

    log(f"subprocess: {' '.join(c if i == 0 else os.path.basename(c) for i, c in enumerate(cmd))}")
    if on_progress:
        on_progress(15, f"Starting Demucs subprocess ({model_name})…")

    stop = threading.Event()

    def _tick():
        p = 15
        while not stop.is_set():
            time.sleep(3)
            if p < 88:
                p += 2
            if on_progress:
                on_progress(p, "Separating stems…")

    threading.Thread(target=_tick, daemon=True).start()

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
            lines.append(line)
    proc.wait()
    stop.set()

    if proc.returncode != 0:
        raise RuntimeError(
            f"demucs subprocess failed (exit {proc.returncode}):\n" +
            "\n".join(lines[-20:])
        )

    stems: dict = {}
    ff = find_ffmpeg()
    for root, _, files in os.walk(temp_out):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in (".wav", ".mp3", ".flac"):
                continue
            name = os.path.splitext(f)[0].lower()
            src  = os.path.join(root, f)
            dst  = os.path.join(output_dir, f"{name}.wav")
            if ext == ".wav":
                shutil.copy2(src, dst)
            else:
                subprocess.run(
                    [ff, "-y", "-i", src,
                     "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", dst],
                    capture_output=True,
                )
            stems[name] = dst

    shutil.rmtree(temp_out, ignore_errors=True)
    return stems


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: demucs_runner.py <input_file> <output_dir> [model]",
              file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) > 3 else "htdemucs"

    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}", file=sys.stderr)
        sys.exit(1)

    log(f"Python  : {sys.executable}")
    log(f"Input   : {input_file}")
    log(f"Output  : {output_dir}")
    log(f"Model   : {model_name}")

    prog(2, "Checking dependencies…")
    try:
        import demucs
        import torch
        log(f"demucs {getattr(demucs, '__version__', '?')} | "
            f"torch {torch.__version__} | CUDA={torch.cuda.is_available()}")
    except ImportError as exc:
        print(f"ERROR: {exc}. Run install.bat to install dependencies.",
              file=sys.stderr)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # Pre-convert to clean WAV to avoid codec edge-cases inside Demucs
    prog(5, "Preparing audio…")
    tmp_wav = os.path.join(output_dir, "_input_converted.wav")
    try:
        to_wav_44100(input_file, tmp_wav)
        working = tmp_wav
        log(f"Pre-converted to WAV: {tmp_wav}")
    except Exception as exc:
        log(f"WAV pre-conversion failed ({exc}) — using original")
        working = input_file

    # ── Try Python API first, subprocess as fallback ──────────────────────────
    stems: dict | None = None

    for attempt_model in ([model_name] if model_name == "htdemucs"
                          else [model_name, "htdemucs"]):
        for runner, label in [
            (run_demucs_api, "Python API"),
            (run_demucs_subprocess, "subprocess"),
        ]:
            try:
                prog(10, f"Starting Demucs ({label}, model={attempt_model})…")
                stems = runner(working, output_dir, attempt_model,
                               on_progress=prog)
                log(f"Separation complete ({label}, model={attempt_model})")
                break
            except Exception as exc:
                log(f"{label} / {attempt_model} failed: {exc}")
        if stems:
            break

    # Cleanup temp input
    if os.path.exists(tmp_wav):
        try:
            os.unlink(tmp_wav)
        except OSError:
            pass

    if not stems:
        print("ERROR: Demucs stem separation failed after all attempts.",
              file=sys.stderr)
        sys.exit(1)

    prog(100, "Done!")
    log(f"Stems: {list(stems.keys())}")
    print(json.dumps({"success": True, "stems": stems}))


if __name__ == "__main__":
    main()
