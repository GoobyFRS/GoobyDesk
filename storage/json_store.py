#!/usr/bin/env python3
"""Generic JSON storage with atomic write support.
Uses temp-file + rename plus optional directory fsync to avoid
corruption on crashes; suitable for small JSON-backed databases.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

JsonValidator = Callable[[Any], bool]

class JsonStore:
    """Generic JSON file store with atomic write semantics.
    Args:
        file_path: Path to the JSON file.
        default_factory: Factory returning default JSON object when file is
            missing or malformed.
        validator: Optional validator for top-level JSON payload.
    """

    def __init__(
        self,
        file_path: str | Path,
        default_factory: Callable[[], Any] | None = None,
        validator: JsonValidator | None = None,
    ) -> None:
        self.path = Path(file_path)
        self._default_factory = default_factory or list
        self._validator = validator
        self._lock = threading.RLock()

    def lock(self) -> threading.RLock:
        """Return the in-process lock used for store operations."""
        return self._lock

    def exists(self) -> bool:
        """Return True if the storage file exists."""
        return self.path.exists()

    def read(self, default: Any | None = None) -> Any:
        """Read JSON payload from disk.
        Returns default_factory output when file is missing or malformed.
        """
        fallback = self._make_default(default)

        if not self.path.exists():
            return fallback

        try:
            with self.path.open("r", encoding="utf-8") as source_file:
                data = json.load(source_file)
        except json.JSONDecodeError:
            logging.warning("JSON STORE - Invalid JSON at %s. Using default.", self.path)
            return fallback
        except OSError as exc:
            logging.error("JSON STORE - Failed reading %s: %s", self.path, exc)
            return fallback

        if self._validator and not self._validator(data):
            logging.warning("JSON STORE - Validation failed at %s. Using default.", self.path)
            return fallback

        return data

    def write(self, data: Any) -> None:
        """Write JSON payload atomically."""
        self.atomic_write(data)

    def atomic_write(self, data: Any) -> None:
        """Atomically persist JSON payload using temp file + replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(self.path.parent),
                    prefix=f"{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp_file:
                    json.dump(data, tmp_file, indent=4)
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                    tmp_path = Path(tmp_file.name)

                os.replace(tmp_path, self.path)

                if os.name != "nt":
                    try:
                        dir_fd = os.open(self.path.parent, os.O_RDONLY)
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    except OSError:
                        logging.debug("JSON STORE - Directory fsync skipped for %s", self.path)
            finally:
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        logging.debug("JSON STORE - Could not clean temp file %s", tmp_path)

    def append(self, item: Any) -> list[Any]:
        """Append item to list-backed JSON file and persist."""
        with self._lock:
            data = self.read(default=[])
            if not isinstance(data, list):
                logging.warning("JSON STORE - Append expected list at %s. Resetting.", self.path)
                data = []
            data.append(item)
            self.atomic_write(data)
            return data

    def update(
        self,
        predicate: Callable[[Any], bool],
        updater: Callable[[Any], Any],
    ) -> tuple[list[Any], bool]:
        """Update the first list item matching predicate.
        Returns updated list and whether a record was changed.
        """
        with self._lock:
            data = self.read(default=[])
            if not isinstance(data, list):
                logging.warning("JSON STORE - Update expected list at %s. Resetting.", self.path)
                data = []

            for index, record in enumerate(data):
                if predicate(record):
                    replacement = updater(record)
                    data[index] = replacement if replacement is not None else record
                    self.atomic_write(data)
                    return data, True

            return data, False

    def delete(self, predicate: Callable[[Any], bool]) -> tuple[list[Any], int]:
        """Delete all list items matching predicate.
        Returns updated list and number of deleted records.
        """
        with self._lock:
            data = self.read(default=[])
            if not isinstance(data, list):
                logging.warning("JSON STORE - Delete expected list at %s. Resetting.", self.path)
                data = []

            updated = [item for item in data if not predicate(item)]
            removed = len(data) - len(updated)

            if removed:
                self.atomic_write(updated)

            return updated, removed

    def validate(self) -> bool:
        """Validate current JSON payload against configured validator."""
        if not self._validator:
            return True
        data = self.read()
        return self._validator(data)

    def backup(self) -> Path:
        """Create a timestamped backup file and return its path."""
        from storage.backup import create_json_backup

        return create_json_backup(self.path)

    def _make_default(self, default: Any | None) -> Any:
        if default is not None:
            return default
        return self._default_factory()
