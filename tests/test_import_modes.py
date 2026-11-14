import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class BackendImportModeTests(unittest.TestCase):
    def test_documented_repository_root_import_mode(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "backend"
        result = subprocess.run(
            [sys.executable, "-c", "import main; assert main.app is not None"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backend_directory_import_mode(self):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-c", "import main; assert main.app is not None"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
