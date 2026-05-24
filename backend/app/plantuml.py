"""PlantUML rendering utilities.

Renders .puml/.uml source strings to PNG images using the local PlantUML JAR.
Requires Java and ~/.local/lib/plantuml.jar.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_JAR = Path.home() / ".local" / "lib" / "plantuml.jar"


def find_plantuml_jar() -> Path | None:
    """Locate the PlantUML JAR file."""
    jar = Path(os.getenv("PLANTUML_JAR", str(_DEFAULT_JAR)))
    return jar if jar.is_file() else None


def is_available() -> bool:
    """Check if PlantUML rendering is available (Java + JAR)."""
    if not find_plantuml_jar():
        return False
    try:
        subprocess.run(
            ["java", "-version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def render_puml_to_png(puml_source: str) -> bytes | None:
    """Render a PlantUML source string to PNG bytes. Returns None on failure."""
    jar = find_plantuml_jar()
    if not jar:
        logger.warning("PlantUML JAR not found at %s", _DEFAULT_JAR)
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "diagram.puml"
        src_path.write_text(puml_source, encoding="utf-8")

        try:
            result = subprocess.run(
                ["java", "-Djava.awt.headless=true", "-jar", str(jar), "-tpng", str(src_path)],
                capture_output=True,
                timeout=30,
                env={**os.environ, "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true"},
            )
            if result.returncode != 0:
                logger.error("PlantUML render failed: %s", result.stderr.decode())
                return None
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.error("PlantUML execution error: %s", e)
            return None

        png_path = Path(tmpdir) / "diagram.png"
        if not png_path.exists():
            logger.error("PlantUML produced no output PNG")
            return None

        return png_path.read_bytes()


def render_multiple(puml_sources: list[str]) -> list[bytes | None]:
    """Render multiple PlantUML diagrams. Returns list of PNG bytes (None for failures)."""
    return [render_puml_to_png(src) for src in puml_sources]
