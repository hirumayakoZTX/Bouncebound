"""Versioned, local high-score storage kept outside gameplay scoring logic."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from collections.abc import Mapping


SAVE_VERSION = 1
SAVE_RELATIVE_PATH = Path("save") / "high_scores.json"
APPLICATION_NAME = "Bouncebound"


@dataclass(frozen=True)
class HighScoreRecord:
    """The small, non-personal record stored for completed campaigns."""

    best_score: int = 0
    last_score: int = 0
    last_stage: int = 0
    version: int = SAVE_VERSION


@dataclass(frozen=True)
class HighScoreSnapshot:
    """Read-only persistence status suitable for exposing through WorldSnapshot."""

    record: HighScoreRecord | None = None
    available: bool = False
    saved: bool | None = None
    new_record: bool | None = None
    message: str = "High score storage is unavailable."


@dataclass(frozen=True)
class _ReadResult:
    record: HighScoreRecord | None
    available: bool
    can_recover: bool
    message: str


class _UnsupportedVersion(ValueError):
    pass


def default_save_path(*, platform: str | None = None,
                      environ: Mapping[str, str] | None = None,
                      home: Path | None = None) -> Path:
    """Return the platform's per-user data path without relying on cwd."""

    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ

    if platform == "darwin":
        home = Path.home() if home is None else Path(home)
        data_root = home / "Library" / "Application Support" / APPLICATION_NAME
    elif platform.startswith("win"):
        local_app_data = environ.get("LOCALAPPDATA")
        if local_app_data and Path(local_app_data).is_absolute():
            data_root = Path(local_app_data) / APPLICATION_NAME
        else:
            home = Path.home() if home is None else Path(home)
            data_root = home / "AppData" / "Local" / APPLICATION_NAME
    else:
        xdg_data = environ.get("XDG_DATA_HOME")
        if xdg_data and Path(xdg_data).is_absolute():
            data_root = Path(xdg_data) / APPLICATION_NAME.lower()
        else:
            home = Path.home() if home is None else Path(home)
            data_root = home / ".local" / "share" / APPLICATION_NAME.lower()
    return data_root / SAVE_RELATIVE_PATH


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate save field: {key}")
        result[key] = value
    return result


def _parse_record(data: object) -> HighScoreRecord:
    if not isinstance(data, dict):
        raise ValueError("Save data must be a JSON object")
    version = data.get("version")
    if type(version) is int and version != SAVE_VERSION:
        raise _UnsupportedVersion(f"Unsupported save version: {version}")
    expected = {"version", "best_score", "last_score", "last_stage"}
    if set(data) != expected:
        raise ValueError("Save data has missing or unknown fields")
    if type(version) is not int:
        raise ValueError("Save version must be an integer")

    for field in ("best_score", "last_score", "last_stage"):
        if type(data[field]) is not int:
            raise ValueError(f"{field} must be an integer")
    best_score = data["best_score"]
    last_score = data["last_score"]
    last_stage = data["last_stage"]
    if best_score < 0 or last_score < 0:
        raise ValueError("Scores cannot be negative")
    if last_stage not in (0, 1, 2, 3):
        raise ValueError("last_stage must be between 0 and 3")
    if last_score > best_score:
        raise ValueError("last_score cannot exceed best_score")
    if last_stage == 0 and (best_score != 0 or last_score != 0):
        raise ValueError("An empty record cannot contain a score")
    return HighScoreRecord(best_score, last_score, last_stage, version)


class HighScoreStore:
    """Loads and atomically updates one local best-score record.

    Pass ``path`` to isolate tests or embed the store elsewhere. The normal
    application supplies the platform-specific path returned by
    :func:`default_save_path`.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        try:
            self.path: Path | None = Path(path) if path is not None else default_save_path()
        except (OSError, RuntimeError):
            self.path = None

    def _read(self) -> _ReadResult:
        if self.path is None:
            return _ReadResult(None, False, False, "High score location is unavailable.")
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream, object_pairs_hook=_reject_duplicate_keys)
        except FileNotFoundError:
            return _ReadResult(HighScoreRecord(), True, True, "No saved high score yet.")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            return _ReadResult(None, False, True, "High score data is invalid.")
        except OSError:
            return _ReadResult(None, False, False, "High score file could not be read.")

        try:
            record = _parse_record(raw)
        except _UnsupportedVersion:
            return _ReadResult(None, False, False, "High score version is unsupported.")
        except (ValueError, TypeError, KeyError):
            return _ReadResult(None, False, True, "High score data is invalid.")
        return _ReadResult(record, True, True, "High score loaded.")

    def load(self) -> HighScoreSnapshot:
        """Read once on application startup; missing data is a normal first run."""

        result = self._read()
        return HighScoreSnapshot(result.record, result.available, message=result.message)

    def save_completed_campaign(self, score: int, last_stage: int) -> HighScoreSnapshot:
        """Save only a completed three-stage campaign and return truthful status."""

        if type(score) is not int or score < 0:
            raise ValueError("Completed campaign score must be a nonnegative integer")
        if type(last_stage) is not int or last_stage != 3:
            raise ValueError("Only a completed Stage 3 campaign can be saved")

        previous = self._read()
        if not previous.can_recover:
            return HighScoreSnapshot(previous.record, False, False, None, previous.message)

        known_previous = previous.record
        new_record = (score > known_previous.best_score
                      if known_previous is not None else None)
        best_score = max(score, known_previous.best_score) if known_previous else score
        updated = HighScoreRecord(best_score, score, last_stage)
        try:
            self._atomic_write(updated)
        except OSError:
            return HighScoreSnapshot(
                known_previous, known_previous is not None, False,
                False if known_previous is not None else None,
                "Score could not be saved.",
            )

        if new_record is True:
            message = "New high score saved."
        elif new_record is False:
            message = "Campaign score saved."
        else:
            message = "Score saved; previous high score was unavailable."
        return HighScoreSnapshot(updated, True, True, new_record, message)

    def _atomic_write(self, record: HighScoreRecord) -> None:
        """Write a sibling temporary file and replace the destination atomically."""

        if self.path is None:
            raise OSError("High score location is unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({
                    "version": record.version,
                    "best_score": record.best_score,
                    "last_score": record.last_score,
                    "last_stage": record.last_stage,
                }, stream, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

