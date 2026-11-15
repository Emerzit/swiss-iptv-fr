"""Non-interactive entry point for the Windows scheduled task; logs remain local."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from update import main


if __name__ == '__main__':
    os.chdir(ROOT)
    logs = ROOT / 'data/logs'
    logs.mkdir(parents=True, exist_ok=True)
    result = 0
    with (logs / 'last-update.log').open('w', encoding='utf-8', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        print('Started:', datetime.now(timezone.utc).isoformat(), flush=True)
        try:
            main()
        except Exception:
            traceback.print_exc()
            result = 1
        print('Exit code:', result, flush=True)
    sys.exit(result)
