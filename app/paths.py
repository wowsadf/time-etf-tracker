from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

APP_DIR = ROOT_DIR / "app"
SNAPSHOTS_DIR = ROOT_DIR / "snapshots"
STATE_DIR = ROOT_DIR / "state"
TEMP_DIR = ROOT_DIR / "temp"
TESTS_DIR = ROOT_DIR / "tests"
MANUAL_INPUTS_DIR = ROOT_DIR / "manual_inputs"

TRACKER_STATE_PATH = STATE_DIR / "tracker_state.json"
LATEST_XLSX_PATH = TEMP_DIR / "latest.xlsx"

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
TESTS_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_INPUTS_DIR.mkdir(parents=True, exist_ok=True)