#!/usr/bin/env python3
"""
WAVEMAKRZ — loop_finder.py  (librosa-based, real BPM-aligned loops)
Usage: python loop_finder.py <input_file> <output_dir> [bpm_override] [bars]
Outputs: WAV loops named e.g. 128bpm_Cmin_8bars_01.wav
"""
import sys, os, json, warnings
warnings.filterwarnings('ignore')

def log(msg): print(f'[LoopFinder] {msg}', file=sys.stderr, flush=True)
def prog(pct, msg=''): print(f'PROGRESS:{pct:.1f} {msg}', flush=True)

def find_ffmpeg():
    import shutil
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in ['../bin/ffmpeg.exe', '../bin/ffmpeg', '../../bin/ffmpeg.exe']:
        c = os.path.normpath(os.path.join(script_dir, rel))
        if os.path.exists(c): return c
    if shutil.which('ffmpeg'): return shutil.which('ffmpeg')
    try:
        import imageio_ffmpeg; exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe): return exe
    except ImportError: pass
    return 'ffmpeg'

def krumhansl_schmuckler(chroma_mean):
    import numpy as np
    major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    def pearson(a, b):
        ma,mb = a.mean(), b.mean()
        n = ((a-ma)*(b-mb)).sum()
        d = np.sqrt(((a-ma)**2).sum()*((b-mb)**2).sum())
        return float(n/d) if d>1e-8 else 0.0
    best, bk, bs = -2.0, 'C', 'major'
    for s in range(12):
        r = np.roll(chroma_mean, -s)
        for p, sc in [(major,'major'),(minor,'minor')]:
            c = pearson(r, p)
            if c > best: best,bk,bs = c, notes[s], sc
    return bk, bs

def main():
    if len(sys.argv) < 3:
        print('Usage: loop_finder.py <input_file> <output_dir> [bpm] [bars]', file=sys.stderr)
        sys.exit(1)

    input_file   = sys.argv[1]
    output_dir   = sys.argv[2]
    bpm_override = float(sys.argv[3]) if len(sys.argv) > 3 else 0
    bars_str     = sys.argv[4] if len(sys.argv) > 4 else '4,8,16'
    bar_lengths  = [int(b) for b in bars_str.split(',') if b.strip().isdigit()]

    if not os.path.exists(input_file):
        print(f'ERROR: {input_file} not found', file=sys.stderr); sys.exit(1)

    try:
        import librosa, librosa.beat, librosa.effects
        import librosa.feature
        import soundfile as sf
        import numpy as np
    except ImportError as e:
        print(f'ERROR: {e}. Run install.bat.', file=sys.stderr); sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # ── Set ffmpeg path so librosa / audioread can find it ───────────────────
    ffmpeg = find_ffmpeg()
    os.environ.setdefault('FFMPEG_BINARY', ffmpeg)
    os.environ['PATH'] = os.path.dirname(ffmpeg) + os.pathsep + os.environ.get('PATH','')

    prog(5, 'Loading audio...')
    log(f'Loading: {os.path.basename(input_file)}')

    # Load stereo at native sr for export quality, mono for analysis
    try:
        y_stereo, sr = librosa.load(input_file, sr=44100, mono=False)
    except Exception as e:
        log(f'Stereo load failed ({e}), loading mono...')
        y_stereo, sr = librosa.load(input_file, sr=44100, mono=True)

    # Mono for analysis
    if y_stereo.ndim == 2:
        y_mono = y_stereo.mean(axis=0)
    else:
        y_mono  = y_stereo
        y_stereo = np.stack([y_stereo, y_stereo])

    duration = len(y_mono) / sr
    log(f'Loaded {duration:.1f}s at {sr}Hz')

    # ── BPM ──────────────────────────────────────────────────────────────────
    prog(15, 'Detecting BPM...')
    if bpm_override and bpm_override > 0:
        bpm = bpm_override
        log(f'Using override BPM: {bpm}')
        beat_frames = None
    else:
        tempo_result, beat_frames = librosa.beat.beat_track(y=y_mono, sr=sr, units='frames')
        bpm = float(tempo_result[0]) if hasattr(tempo_result,'__len__') else float(tempo_result)
        log(f'Detected BPM: {bpm:.2f}')

    # ── Key ───────────────────────────────────────────────────────────────────
    prog(25, 'Detecting key...')
    y_harm = librosa.effects.harmonic(y_mono, margin=4)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr, bins_per_octave=36)
    key, scale = krumhansl_schmuckler(chroma.mean(axis=1))
    key_str = f"{key}{'min' if scale=='minor' else 'maj'}"
    log(f'Key: {key} {scale}')

    # ── Beat grid ────────────────────────────────────────────────────────────
    prog(35, 'Building beat grid...')
    spb    = 60.0 / max(bpm, 1)   # seconds per beat
    spbar  = spb * 4              # seconds per 4/4 bar

    # Convert beat_frames to sample positions
    if beat_frames is not None and len(beat_frames) > 0:
        beat_samples = librosa.frames_to_samples(beat_frames, hop_length=512)
    else:
        # Synthetic grid
        beat_samples = (np.arange(0, duration, spb) * sr).astype(int)
        beat_samples = beat_samples[beat_samples < len(y_mono)]

    # ── Extract loops ─────────────────────────────────────────────────────────
    loop_files = []
    bpm_int    = int(round(bpm))
    n_bar_types = len(bar_lengths)

    for bar_idx, num_bars in enumerate(bar_lengths):
        pct_start = 40 + bar_idx * (50 // n_bar_types)
        prog(pct_start, f'Generating {num_bars}-bar loops...')

        n_samples = int(sr * spbar * num_bars)
        if n_samples > y_stereo.shape[-1]:
            log(f'Skip {num_bars} bars — audio too short ({duration:.1f}s)')
            continue

        # Score each downbeat by RMS energy of the following segment
        scores = []
        for bs in beat_samples[::4]:    # every 4th beat = downbeat
            end = bs + n_samples
            if end > y_stereo.shape[-1]: break
            seg = y_mono[bs:bs + min(n_samples, 4*sr)]
            scores.append((float(np.sqrt(np.mean(seg**2))), int(bs)))

        if not scores:
            log(f'No valid start points for {num_bars} bars'); continue

        # Sort by energy, pick top 3 non-overlapping starts
        scores.sort(reverse=True)
        used, count, max_loops = [], 0, 3

        for energy, start in scores:
            if count >= max_loops: break
            if any(abs(start - u) < n_samples * 0.75 for u in used): continue
            used.append(start)

            # Extract loop
            end   = start + n_samples
            loop  = y_stereo[:, start:end].copy()

            # Fade in/out to prevent clicks (5ms)
            fade_n = min(int(sr * 0.005), 256)
            fi = np.linspace(0, 1, fade_n)
            fo = np.linspace(1, 0, fade_n)
            loop[:, :fade_n]  *= fi
            loop[:, -fade_n:] *= fo

            # Normalize — leave ~1dB headroom
            peak = float(np.abs(loop).max())
            if peak > 0.89:
                loop *= 0.89 / peak

            # Export as 44.1kHz / 24-bit WAV
            out_name = f'{bpm_int}bpm_{key_str}_{num_bars}bars_{count+1:02d}.wav'
            out_path = os.path.join(output_dir, out_name)
            sf.write(out_path, loop.T, sr, subtype='PCM_24')
            loop_files.append(out_path)
            log(f'Loop: {out_name} ({n_samples/sr:.2f}s, energy={energy:.4f})')
            count += 1

        prog(pct_start + (50 // n_bar_types) - 5, f'{count} × {num_bars}-bar loops created')

    prog(98, 'Finalizing...')
    prog(100, 'Done!')
    log(f'Total loops: {len(loop_files)}')
    print(json.dumps({
        'success': True,
        'loops':   loop_files,
        'bpm':     bpm,
        'key':     key,
        'scale':   scale,
        'count':   len(loop_files),
    }))

if __name__ == '__main__':
    main()
