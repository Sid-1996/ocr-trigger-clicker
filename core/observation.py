"""Shadow Observation — unified recognition result (Phase 1, minimal).

Purpose: pure translation of legacy OCR/Match results into a common
Observation shape. No OCR, no matching, no cache mutation, no Rule
state change. Shadow mode only: Legacy result -> adapter -> comparison.

Design: keep fields that already have reliable sources in
core/02_ocr_engine.OcrResult and core/11_template_matching.MatchResult.
All fields beyond the common core are optional.

# ponytail: Phase 1 shadow-only — no consumer yet; if Phase 2 does not
# promote Observation to decision path by v0.5.0, delete this module
# (single commit rollback, ~265 lines). Keeps shadow debt bounded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Observation:
    """Minimal unified recognition result.

    Common core mirrors what OcrResult/MatchResult already carry:
    - type: "ocr" | "template" | "cv" (future)
    - value: text (ocr) or template_name (template)
    - confidence: 0..1
    - bbox: (x, y, w, h) in image pixel coords
    - roi: source roi dict (may be empty for full-window)
    - ts: monotonic timestamp
    - meta: optional source-specific extras
    """

    type: str
    value: str
    confidence: float
    bbox: tuple[int, int, int, int]
    roi: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)
    meta: dict = field(default_factory=dict)

    @property
    def x(self) -> int:
        return self.bbox[0]

    @property
    def y(self) -> int:
        return self.bbox[1]

    @property
    def w(self) -> int:
        return self.bbox[2]

    @property
    def h(self) -> int:
        return self.bbox[3]

    @property
    def center_x(self) -> int:
        return self.bbox[0] + self.bbox[2] // 2

    @property
    def center_y(self) -> int:
        return self.bbox[1] + self.bbox[3] // 2

    @property
    def text(self) -> str:
        """Compat: OcrResult/MatchResult both expose .text."""
        return self.value


def ocr_to_observations(
    results: list,
    roi: dict | None = None,
) -> list[Observation]:
    """Pure translation: list[OcrResult] -> list[Observation].

    Does not OCR, does not mutate cache. Accepts empty list.
    """
    if not results:
        return []
    now = time.monotonic()
    roi = roi or {}
    out: list[Observation] = []
    for r in results:
        try:
            bbox = (int(r.x), int(r.y), int(r.w), int(r.h))
            out.append(
                Observation(
                    type="ocr",
                    value=str(getattr(r, "text", "")),
                    confidence=float(getattr(r, "confidence", 0.0)),
                    bbox=bbox,
                    roi=dict(roi),
                    ts=now,
                    meta={},
                )
            )
        except Exception:
            # Never crash the shadow path on malformed result
            continue
    return out


def template_to_observations(
    results: list,
    roi: dict | None = None,
) -> list[Observation]:
    """Pure translation: list[MatchResult] -> list[Observation]."""
    if not results:
        return []
    now = time.monotonic()
    roi = roi or {}
    # match_template may return (list, best_below) when return_best=True;
    # caller unwraps before calling adapter. Guard just in case.
    if isinstance(results, tuple):
        results = results[0]
    out: list[Observation] = []
    for r in results:
        try:
            bbox = (int(r.x), int(r.y), int(r.w), int(r.h))
            out.append(
                Observation(
                    type="template",
                    value=str(getattr(r, "text", getattr(r, "template_name", ""))),
                    confidence=float(getattr(r, "confidence", 0.0)),
                    bbox=bbox,
                    roi=dict(roi),
                    ts=now,
                    meta={"template_name": str(getattr(r, "template_name", ""))},
                )
            )
        except Exception:
            continue
    return out


def compare_ocr_observations(
    ocr_results: list,
    observations: list[Observation],
) -> dict:
    """Compare legacy OcrResult list vs Observation list for shadow diagnostics.

    Returns a tiny dict suitable for debug logging. No side effects.
    Only reports difference; caller decides whether to log.
    """
    try:
        if len(ocr_results) != len(observations):
            return {"mismatch": "count", "legacy": len(ocr_results), "obs": len(observations)}
        for r, o in zip(ocr_results, observations):
            if (
                str(getattr(r, "text", "")) != o.value
                or int(getattr(r, "x", 0)) != o.bbox[0]
                or int(getattr(r, "y", 0)) != o.bbox[1]
                or int(getattr(r, "w", 0)) != o.bbox[2]
                or int(getattr(r, "h", 0)) != o.bbox[3]
                or abs(float(getattr(r, "confidence", 0.0)) - o.confidence) > 1e-6
            ):
                return {
                    "mismatch": "content",
                    "legacy_text": str(getattr(r, "text", "")),
                    "obs_value": o.value,
                }
        return {"mismatch": None}
    except Exception as e:
        return {"mismatch": "error", "error": str(e)}


def compare_template_observations(
    match_results: list,
    observations: list[Observation],
) -> dict:
    try:
        if isinstance(match_results, tuple):
            match_results = match_results[0]
        if len(match_results) != len(observations):
            return {"mismatch": "count", "legacy": len(match_results), "obs": len(observations)}
        for r, o in zip(match_results, observations):
            if (
                int(getattr(r, "x", 0)) != o.bbox[0]
                or int(getattr(r, "y", 0)) != o.bbox[1]
                or int(getattr(r, "w", 0)) != o.bbox[2]
                or int(getattr(r, "h", 0)) != o.bbox[3]
                or abs(float(getattr(r, "confidence", 0.0)) - o.confidence) > 1e-6
            ):
                return {"mismatch": "bbox_or_conf", "legacy": f"{r.x},{r.y}", "obs": f"{o.bbox}"}
        return {"mismatch": None}
    except Exception as e:
        return {"mismatch": "error", "error": str(e)}


if __name__ == "__main__":
    # Minimal self-check: assert-based, no framework
    from core.observation import (
        Observation,
        compare_ocr_observations,
        compare_template_observations,
        ocr_to_observations,
        template_to_observations,
    )

    # OcrResult compat
    class FakeOcr:
        def __init__(self, text, x, y, w, h, confidence):
            self.text = text
            self.x = x
            self.y = y
            self.w = w
            self.h = h
            self.confidence = confidence

    # Empty
    assert ocr_to_observations([]) == []
    assert template_to_observations([]) == []
    # Tuple guard
    assert template_to_observations(([], -1.0)) == []

    # Single OCR
    r = FakeOcr("hello", 10, 20, 30, 40, 0.9)
    obs = ocr_to_observations([r], {"x": 10, "y": 20, "w": 30, "h": 40})
    assert len(obs) == 1
    assert obs[0].type == "ocr"
    assert obs[0].value == "hello"
    assert obs[0].bbox == (10, 20, 30, 40)
    assert obs[0].confidence == 0.9
    assert obs[0].center_x == 25
    assert obs[0].text == "hello"
    assert obs[0].roi == {"x": 10, "y": 20, "w": 30, "h": 40}
    assert compare_ocr_observations([r], obs)["mismatch"] is None

    # Mismatch detection
    r2 = FakeOcr("world", 10, 20, 30, 40, 0.9)
    assert compare_ocr_observations([r2], obs)["mismatch"] == "content"
    assert compare_ocr_observations([r, r2], obs)["mismatch"] == "count"

    # Malformed entry skipped, not crash
    class Bad:
        pass

    assert ocr_to_observations([Bad()]) == []

    # MatchResult compat
    class FakeMatch:
        def __init__(self, x, y, w, h, confidence, name="inline"):
            self.x = x
            self.y = y
            self.w = w
            self.h = h
            self.confidence = confidence
            self.template_name = name
            self.text = name

    m = FakeMatch(1, 2, 3, 4, 0.77, "btn_ok")
    obs2 = template_to_observations([m], {"x": 0, "y": 0, "w": 10, "h": 10})
    assert len(obs2) == 1
    assert obs2[0].type == "template"
    assert obs2[0].value == "btn_ok"
    assert obs2[0].bbox == (1, 2, 3, 4)
    assert obs2[0].meta["template_name"] == "btn_ok"
    assert compare_template_observations([m], obs2)["mismatch"] is None
    assert compare_template_observations([m, m], obs2)["mismatch"] == "count"

    print("=== Observation Self-Check ===")
    print(
        "  [OK] ocr/template adapters, bbox/confidence mapping, mismatch detection, empty/tuple guard"
    )
    print("=== All checks passed ===")
