"""Optional presentation resources. Importing or loading images initializes no SDL subsystem."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pygame


ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"
LOGGER = logging.getLogger(__name__)


def _dimensions(size: tuple[int, int]) -> None:
    if (not isinstance(size, tuple) or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)):
        raise ValueError("Native image size must contain two positive integers")


@dataclass(frozen=True)
class ImageAsset:
    """Cached surfaces are shared: treat them as read-only, or copy before editing."""

    surface: pygame.Surface
    source_size: tuple[int, int]
    is_fallback: bool = False


@dataclass(frozen=True)
class SafeSound:
    """A sound handle that stays a safe no-op without an available mixer."""

    _sound: pygame.mixer.Sound | None = None

    @property
    def is_silent(self) -> bool:
        if self._sound is None:
            return True
        try:
            return not pygame.mixer.get_init()
        except (pygame.error, NotImplementedError):
            return True

    def _call(self, method: str, *args, **kwargs):
        if self.is_silent:
            return None
        try:
            return getattr(self._sound, method)(*args, **kwargs)
        except (pygame.error, OSError, NotImplementedError):
            # A device may disappear after loading. Playback cannot stop gameplay.
            return None

    def play(self, *args, **kwargs):
        return self._call("play", *args, **kwargs)

    def stop(self) -> None:
        self._call("stop")

    def fadeout(self, milliseconds: int) -> None:
        self._call("fadeout", milliseconds)

    def set_volume(self, volume: float) -> None:
        self._call("set_volume", volume)


SILENT_SOUND = SafeSound()


class AssetManager:
    """Cache optional images/sounds below one root, independent of the shell CWD.

    Images must match their declared native dimensions. Scaling is integer-only
    and nearest-neighbor. Invalid caller paths/sizes raise ValueError; resource
    failures log once per path and return cached fallbacks. No World references
    or authoritative gameplay data belong here.
    """

    def __init__(self, root: str | Path | None = None, *, audio_enabled: bool = False) -> None:
        self.root = Path(root).resolve() if root is not None else ASSET_ROOT
        self.audio_enabled = audio_enabled
        self._paths: dict[Path, Path] = {}
        self._sources: dict[tuple[Path, tuple[int, int]], ImageAsset] = {}
        self._scaled: dict[tuple[Path, tuple[int, int], int], ImageAsset] = {}
        self._sounds: dict[Path, SafeSound] = {}
        self._warned: set[tuple[str, Path]] = set()
        self._audio_failed = False

    def resolve_path(self, name: str | Path) -> Path:
        if not isinstance(name, (str, Path)) or not str(name).strip():
            raise ValueError("Asset name must be a nonempty relative path")
        name = Path(name)
        if name.is_absolute():
            raise ValueError("Asset names must be relative to the asset root")
        if name in self._paths:
            return self._paths[name]
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Asset paths must remain below the asset root")
        self._paths[name] = path
        return path

    def _warn(self, category: str, path: Path, error: Exception) -> None:
        key = (category, path)
        if key not in self._warned:
            self._warned.add(key)
            LOGGER.warning("Optional %s %s unavailable: %s", category,
                           path.relative_to(self.root), error)

    @staticmethod
    def _placeholder(size: tuple[int, int]) -> pygame.Surface:
        surface = pygame.Surface(size, pygame.SRCALPHA)
        surface.fill((43, 48, 65, 255))
        pygame.draw.rect(surface, (225, 92, 175), surface.get_rect(), width=1)
        pygame.draw.line(surface, (225, 92, 175), (0, 0), (size[0]-1, size[1]-1))
        pygame.draw.line(surface, (225, 92, 175), (size[0]-1, 0), (0, size[1]-1))
        return surface

    def load_image(self, name: str | Path, *, native_size: tuple[int, int] = (16, 16),
                   scale: int = 1) -> ImageAsset:
        _dimensions(native_size)
        if type(scale) is not int or scale < 1:
            raise ValueError("Pixel scale must be a positive integer")
        path = self.resolve_path(name)
        key = (path, native_size, scale)
        if key in self._scaled:
            return self._scaled[key]
        source_key = (path, native_size)
        if source_key not in self._sources:
            fallback = False
            try:
                surface = pygame.image.load(str(path))
                if surface.get_size() != native_size:
                    raise ValueError(f"Expected native size {native_size}, got {surface.get_size()}")
                if pygame.display.get_surface() is not None:
                    surface = surface.convert_alpha()
            except (OSError, pygame.error, ValueError) as error:
                self._warn("image", path, error)
                surface = self._placeholder(native_size)
                fallback = True
            self._sources[source_key] = ImageAsset(surface, native_size, fallback)
        source = self._sources[source_key]
        surface = (source.surface if scale == 1 else pygame.transform.scale(
            source.surface, (native_size[0] * scale, native_size[1] * scale)))
        result = ImageAsset(surface, source.source_size, source.is_fallback)
        self._scaled[key] = result
        return result

    def load_sound(self, name: str | Path) -> SafeSound:
        path = self.resolve_path(name)
        if path in self._sounds:
            return self._sounds[path]
        result = SILENT_SOUND
        if self.audio_enabled and not self._audio_failed:
            try:
                # Missing optional files never initialize an audio device.
                if not path.is_file():
                    raise FileNotFoundError("File does not exist")
                try:
                    if not pygame.mixer.get_init():
                        pygame.mixer.init()
                except (pygame.error, OSError, NotImplementedError):
                    self._audio_failed = True
                    raise
                result = SafeSound(pygame.mixer.Sound(str(path)))
            except (OSError, pygame.error, NotImplementedError) as error:
                self._warn("sound", path, error)
        self._sounds[path] = result
        return result

    def clear_cache(self) -> None:
        """Reload on next request, including failed files/devices. Does not close SDL."""
        self._paths.clear()
        self._sources.clear()
        self._scaled.clear()
        self._sounds.clear()
        self._warned.clear()
        self._audio_failed = False
