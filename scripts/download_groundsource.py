"""Download the pinned public archive, resuming a local incomplete download.

Four concurrent bounded range requests avoid one long transfer. This only accesses the
public source URL, never project credentials or a database. Run locally, not
inside the production web service. The final file must match publisher MD5.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import shutil
import time

import requests

from extract_groundsource import SOURCE_BYTES, SOURCE_MD5

DOWNLOAD_URL = "https://zenodo.org/records/18647054/files/groundsource_2026.parquet?download=1"


def download():
    target = Path("data/raw/scientific/groundsource_2026.parquet")
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = target.stat().st_size if target.exists() else 0
    if prefix > SOURCE_BYTES:
        raise ValueError("Existing source is larger than the pinned archive; inspect it first.")
    remaining = SOURCE_BYTES - prefix
    step = 8 * 1024 * 1024
    count = (remaining + step - 1) // step
    prefix_marker = target.with_suffix(".parquet.parts_prefix")
    same_prefix_cache = prefix_marker.exists() and prefix_marker.read_text().strip() == str(prefix)

    def part(index):
        start = prefix + index * step
        end = min(start + step, SOURCE_BYTES) - 1
        path = target.with_suffix(f".parquet.part{index}")
        if start > end:
            return None
        # Cache is only a transport optimization. Final publisher checksum still
        # covers every byte (including reused pieces) before accepting the file.
        marker = path.with_suffix(path.suffix + ".range")
        identity = f"{start}-{end}/{SOURCE_BYTES}"
        if (path.exists() and path.stat().st_size == end - start + 1
                and (same_prefix_cache or (marker.exists() and marker.read_text().strip() == identity))):
            return path
        for attempt in range(3):
            try:
                with requests.get(DOWNLOAD_URL, headers={"Range": f"bytes={start}-{end}"},
                                  stream=True, timeout=(20, 90)) as response:
                    response.raise_for_status()
                    expected = f"bytes {start}-{end}/{SOURCE_BYTES}"
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise ValueError("Publisher did not return the requested byte range.")
                    with path.open("wb") as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            stream.write(chunk)
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if path.stat().st_size != end - start + 1:
            raise ValueError("Incomplete range download; source not accepted.")
        marker.write_text(identity)
        print(f"Completed part {index + 1}: {end - start + 1} bytes", flush=True)
        return path

    parts = []
    if remaining:
        print(f"Resuming from {prefix} of {SOURCE_BYTES} bytes", flush=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            parts = [p for p in pool.map(part, range(count)) if p is not None]
        combined = target.with_suffix(".parquet.download")
        with combined.open("wb") as output:
            if prefix:
                with target.open("rb") as source:
                    shutil.copyfileobj(source, output)
            for path in parts:
                with path.open("rb") as source:
                    shutil.copyfileobj(source, output)
    else:
        combined = target
    digest = hashlib.md5()
    with combined.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if combined.stat().st_size != SOURCE_BYTES or digest.hexdigest() != SOURCE_MD5:
        raise ValueError("Publisher checksum mismatch; no source accepted.")
    if combined != target:
        combined.replace(target)
    for path in parts:
        path.unlink()  # Only the exact temporary range files created above.
        path.with_suffix(path.suffix + ".range").unlink(missing_ok=True)
    prefix_marker.unlink(missing_ok=True)
    print("Publisher checksum verified; archive complete.", flush=True)


if __name__ == "__main__":
    download()
