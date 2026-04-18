import os


def safe_filename(filename: str) -> str:
    """Strip directory components from a filename to prevent path traversal."""
    return os.path.basename(filename.replace("\\", "/"))
