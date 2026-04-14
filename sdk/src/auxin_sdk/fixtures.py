"""Workspace image fixture sampler.

Provides labelled image fixtures for testing the Gemini safety oracle (Phase 1D).
Images live in /sdk/fixtures/images/; labels are in labels.json.

Phase 1B: images are 4-byte JPEG stubs (SOI+EOI).  Replace with real workspace
photos before running Phase 1D's eval harness against the Gemini API.
"""

from __future__ import annotations

import json
import random as _random
from pathlib import Path

# /sdk/src/auxin_sdk/fixtures.py → .parent×3 → /sdk/
_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "images"


def sample_workspace_image(
    rng: _random.Random | None = None,
    fixtures_dir: Path | str | None = None,
) -> tuple[Path, str]:
    """
    Return a random (image_path, label) pair from the fixture library.

    Parameters
    ----------
    rng
        Seeded :class:`random.Random` instance for reproducible sampling.
        Uses the global RNG if ``None``.
    fixtures_dir
        Override the default fixture directory — useful in tests that need
        an isolated fixture set.

    Returns
    -------
    (path, label)
        path  — absolute :class:`~pathlib.Path` to the image file.
        label — ground-truth label: ``"clear"`` or ``"obstacle"``.

    Raises
    ------
    FileNotFoundError
        If the fixture directory or labels.json does not exist.
    """
    base = Path(fixtures_dir) if fixtures_dir is not None else _FIXTURES_DIR
    labels_file = base / "labels.json"

    if not labels_file.exists():
        raise FileNotFoundError(f"labels.json not found at {labels_file}")

    labels: dict[str, str] = json.loads(labels_file.read_text(encoding="utf-8"))
    filenames = list(labels.keys())

    chosen = rng.choice(filenames) if rng is not None else _random.choice(filenames)
    return base / chosen, labels[chosen]


def all_fixture_images(
    fixtures_dir: Path | str | None = None,
) -> list[tuple[Path, str]]:
    """
    Return all (image_path, label) pairs — used by the Phase 1D eval harness.

    Returns pairs in sorted filename order for deterministic evaluation.
    """
    base = Path(fixtures_dir) if fixtures_dir is not None else _FIXTURES_DIR
    labels_file = base / "labels.json"

    if not labels_file.exists():
        raise FileNotFoundError(f"labels.json not found at {labels_file}")

    labels: dict[str, str] = json.loads(labels_file.read_text(encoding="utf-8"))
    return [(base / fname, label) for fname, label in sorted(labels.items())]
