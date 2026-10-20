"""PhotoPort launcher script."""

import sys
from pathlib import Path

# Ensure the src directory is in the Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from photoport.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
