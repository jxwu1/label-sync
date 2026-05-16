from pathlib import Path

from app.config import CONFIG


def list_input_files() -> list[Path]:
    """Return all non-hidden files in the input directory, sorted by name."""
    return sorted(
        (
            path
            for path in CONFIG.input_dir.iterdir()
            if path.is_file() and not path.name.startswith(".")
        ),
        key=lambda p: p.name,
    )
