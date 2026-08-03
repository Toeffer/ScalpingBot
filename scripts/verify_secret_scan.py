"""Prove that the configured scanner detects an ephemeral synthetic secret."""

from __future__ import annotations

import tempfile
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.settings import default_settings


def main() -> int:
    """Return success only when detect-secrets rejects the probe file."""
    access_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    with tempfile.TemporaryDirectory(prefix="secret-scan-probe-") as directory:
        probe = Path(directory) / "probe.txt"
        probe.write_text(f"aws_access_key_id = {access_key}\n", encoding="utf-8")
        secrets = SecretsCollection()
        with default_settings():
            secrets.scan_file(str(probe))
    if not secrets.data:
        print("secret scanner failed to detect the synthetic probe")
        return 1
    print("secret scanner detected the synthetic probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
