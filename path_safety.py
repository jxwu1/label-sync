import os


def safe_filename(filename: str) -> str:
    return os.path.basename(filename.replace("\\", "/"))
