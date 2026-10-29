import subprocess
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
GENERATED_DIRS = ("logs", "market")


def generated_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for top in GENERATED_DIRS
        for path in sorted((root / top).rglob("*"))
        if path.is_file()
    }


def test_generator_reproduces_committed_sample(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SAMPLE_DIR / "generate.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    assert generated_files(tmp_path) == generated_files(SAMPLE_DIR)


def test_sample_stays_small() -> None:
    assert sum(len(data) for data in generated_files(SAMPLE_DIR).values()) < 1_000_000
