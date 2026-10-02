from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

SNAPSHOTS_DIR = ROOT_DIR / "snapshots"
STATE_DIR = ROOT_DIR / "state"
TEMP_DIR = ROOT_DIR / "temp"

TRACKER_STATE_PATH = STATE_DIR / "tracker_state.json"
LATEST_XLSX_PATH = TEMP_DIR / "latest.xlsx"
