from __future__ import annotations

import subprocess
import sys
from typing import Callable

ProgressCallback = Callable[[str], None]


def run_command(
    cmd: list[str],
    *,
    verbose: bool = False,
    progress: ProgressCallback | None = None,
    label: str | None = None,
) -> tuple[int, str]:
    """
    Run a command and return (returncode, combined_output).
    When verbose is True, stream output to stderr while collecting it.
    """
    if progress and label:
        progress(f"Running {label}: {' '.join(cmd)}")

    if verbose:
        streaming_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines: list[str] = []
        if streaming_proc.stdout is None:
            raise RuntimeError("Subprocess stdout is unexpectedly None")
        for line in streaming_proc.stdout:
            lines.append(line)
            print(line, end="", file=sys.stderr, flush=True)
        streaming_proc.wait()
        return streaming_proc.returncode, "".join(lines)

    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    combined_output = (completed.stderr or "") + (("\n" + completed.stdout) if completed.stdout else "")
    return completed.returncode, combined_output
