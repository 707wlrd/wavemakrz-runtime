#!/usr/bin/env python3
"""
WAVEMAKRZ — analyze.py  (librosa-based, real BPM + Key detection)
Usage: python analyze.py <audio_file>
Output: JSON {bpm, key, scale, duration, loudness, tempo_confidence, sample_rate}
"""
import sys, os, json, warnings
warnings.filterwarnings('ignore')

def log(msg): print(f'[Analyze] {msg}', file=sys.stderr, flush=True)

def find_ffmpeg():
    """Locate ffmpeg: local bin → system → imageio_ffmpeg bundled."""
    import shutil
    # 1. Local bin/ next to project
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in ['../bin/ffmpeg.exe', '../bin/ffmpeg', '../../bin/ffmpeg.exe', '../../bin/ffmpeg']:
        c = os.path.normpath(os.path.join(script_dir, rel))
        if os.path.exists(c): return c
    # 2. System PATH
    if shutil.which('ffmpeg'): return shutil.which('ffmpeg')
    # 3. imageio_ffmpeg bundled binary (installed in venv with librosa)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe): return exe
    except ImportError: pass
    return 'ffmpeg'

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: analyze.py <audio_file>'})); sys.exit(1)

    path_in = sys.argv[1]
    if not os.path.exists(path_in):
        print(json.dumps({'error': f'File not found: {path_in}'})); sys.exit(1)

    try:
        import librosa
        import librosa.feature
        import numpy as np
        import soundfile as sf
    except ImportError as e:
        print(json.dumps({'error': f'Missing dependency: {e}. Run install.bat to set up the environment.'}))
        sys.exit(1)

    try:
        # ── Tell librosa to use our local ffmpeg ──────────────────────────────
        ffmpeg_path = find_ffmpeg()
        os.environ.setdefault('FFMPEG_BINARY', ffmpeg_path)
        os.environ.setdefault('PATH', os.path.dirname(ffmpeg_path) + os.pathsep + os.environ.get('PATH',''))
        log(f'ffmpeg: {ffmpeg_path}')

        # ── Load audio (mono, 22050 Hz, max 45s — enough for BPM+key) ──────────
        log(f'Loading: {os.path.basename(path_in)}')
        y, sr = librosa.load(path_in, sr=22050, mono=True, duration=45)
        log(f'Loaded {len(y)/sr:.1f}s at {sr}Hz')

        # ── Real audio duration (full file) ───────────────────────────────────
        try:
            info     = sf.info(path_in)
            duration = info.duration
        except Exception:
            duration = librosa.get_duration(y=y, sr=sr)

        # ── BPM detection ─────────────────────────────────────────────────────
        log('Detecting BPM...')

        # hop=256 gives 2× finer BPM resolution vs hop=512 (avoids ±1 rounding errors)
        hop = 256
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)

        # Method 1: tempogram-based static BPM — more accurate than beat_track
        # for tracks with constant tempo (electronic, pop, hip-hop, etc.)
        static_bpm = float(librosa.feature.tempo(
            onset_envelope=onset_env, sr=sr, hop_length=hop
        )[0])

        # Method 2: beat_track seeded with the static estimate.
        # tightness=100 enforces strict constant-tempo assumption (no rubato).
        tempo_bt, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, hop_length=hop,
            start_bpm=static_bpm, tightness=100
        )
        beat_bpm = float(tempo_bt[0] if hasattr(tempo_bt, '__len__') else tempo_bt)

        # Weighted blend — feature.tempo is more reliable for static-tempo content
        bpm_raw = 0.6 * static_bpm + 0.4 * beat_bpm

        # Round to nearest integer: music-production BPMs are always integers.
        # This eliminates the ±1 quantisation drift (e.g. raw=128.7 → 128, not 129).
        bpm = float(round(bpm_raw))

        bpm_confidence = float(min(1.0, onset_env.mean() * 2))
        log(f'BPM: {bpm:.0f} (raw={bpm_raw:.2f}, static={static_bpm:.2f}, beat={beat_bpm:.2f}, conf={bpm_confidence:.2f})')

        # ── Key detection via chroma + Krumhansl-Schmuckler ───────────────────
        log('Detecting key...')
        # chroma_stft is 5-10x faster than chroma_cqt, accurate enough for key detection
        chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=512, n_fft=4096)
        chroma_mean = chroma.mean(axis=1)

        key_name, scale = krumhansl_schmuckler(chroma_mean)
        log(f'Key: {key_name} {scale}')

        # ── Loudness (integrated RMS → dBFS) ─────────────────────────────────
        rms = librosa.feature.rms(y=y)[0]
        rms_db = float(librosa.amplitude_to_db(rms, ref=1.0).mean())

        # ── Build result ──────────────────────────────────────────────────────
        result = {
            'bpm':               int(bpm),
            'key':               key_name,
            'scale':             scale,
            'duration':          round(duration, 2),
            'loudness':          round(rms_db, 1),
            'tempo_confidence':  round(bpm_confidence, 3),
            'sample_rate':       sr,
        }
        log(f'Result: {result}')
        print(json.dumps(result))
        sys.exit(0)

    except Exception as e:
        import traceback
        msg = f'{e}\n{traceback.format_exc()}'
        log(f'Error: {msg}')
        print(json.dumps({'error': str(e)}))
        sys.exit(1)


def krumhansl_schmuckler(chroma_mean):
    """Detect musical key using Krumhansl-Schmuckler profiles."""
    import numpy as np
    major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']

    def pearson(a, b):
        ma, mb = a.mean(), b.mean()
        num = ((a-ma)*(b-mb)).sum()
        den = np.sqrt(((a-ma)**2).sum() * ((b-mb)**2).sum())
        return float(num/den) if den > 1e-8 else 0.0

    best, bk, bs = -2.0, 'C', 'major'
    for shift in range(12):
        r = np.roll(chroma_mean, -shift)
        for profile, scale in [(major,'major'), (minor,'minor')]:
            c = pearson(r, profile)
            if c > best:
                best, bk, bs = c, notes[shift], scale
    return bk, bs


if __name__ == '__main__':
    main()
