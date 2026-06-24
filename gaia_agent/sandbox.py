"""Minimal Python execution sandbox (subprocess + timeout).

Used by the math/code agents so answers come from real execution rather than
the LLM simulating code in its head.
"""
import os
import sys
import subprocess
import tempfile


def run_python(code: str, timeout: int = 12, extra_files: dict = None) -> str:
    """Execute `code` in a separate process; return stdout (or stderr/timeout).

    extra_files: optional {filename: bytes} written next to the script (e.g. a
    `.py` attachment the question refers to, or a data file).
    """
    workdir = tempfile.mkdtemp(prefix="gaia_sbx_")
    script = os.path.join(workdir, "main.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(code)
    if extra_files:
        for name, data in extra_files.items():
            mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
            with open(os.path.join(workdir, name), mode) as f:
                f.write(data)
    try:
        r = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=timeout, cwd=workdir,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if out:
            return out
        return f"[no stdout] {err}" if err else "[no output]"
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as e:
        return f"[exec error] {e}"
    finally:
        try:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
