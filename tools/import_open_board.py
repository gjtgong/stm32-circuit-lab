#!/usr/bin/env python3
"""Convert the acquired PE.JADO EasyEDA PCB source to OpenBoardData.

The source document is intentionally kept outside the web application.  This
module is a small, deterministic converter for the checked-in source and its
Gerber outline; it does not invoke EasyEDA, a shell, or any external parser.
The generated JavaScript is a UMD module so the same evidence can be inspected
from Node tests and consumed by the browser renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "references/open-board/EasyEDA_F103ZET6.Pcb.api.json"
DEFAULT_GERBER = ROOT / "references/open-board/gerber/Gerber_BoardOutline.GKO"
DEFAULT_OUTPUT = ROOT / "static/open-board-data.js"
RAW_UNITS_MM = 0.254


def _number(value: str | int | float | None, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: str | int | float | None, default: int | None = None) -> int | None:
    number = _number(value)
    if number is None:
        return default
    return int(number)


def _mm_length(value: str | int | float | None, default: float | None = None) -> float | None:
    """Convert an EasyEDA raw length to millimetres."""

    number = _number(value, default)
    if number is None:
        return None
    return round(number * RAW_UNITS_MM, 6)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _id_for(parts: Sequence[str], kind: str) -> str:
    """Return the EasyEDA gId for a source record.

    EasyEDA's record layouts are type-specific.  Keeping this in one place
    makes it harder to accidentally manufacture IDs when a field is empty.
    """

    indexes = {
        "TRACK": 5,
        "VIA": 6,
        "PAD": 12,
        "TEXT": 13,
        "ARC": 6,
        "SOLIDREGION": 5,
        "COPPERAREA": 7,
        "RECT": 6,
        "HOLE": 4,
        "CIRCLE": 6,
        "DIMENSION": 3,
    }
    if kind == "SVGNODE":
        try:
            node = json.loads(parts[1])
            value = node.get("gId") or node.get("attrs", {}).get("id")
            if value:
                return str(value)
        except (IndexError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return "svg-unknown"
    index = indexes.get(kind)
    if index is not None and index < len(parts) and parts[index]:
        return parts[index]
    # This path is only for malformed/anonymous source geometry.  It is
    # deterministic and visibly identifies the record rather than dropping it.
    digest = hashlib.sha1("~".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{kind.lower()}-{digest}"


def _parse_xy_pairs(value: str) -> list[list[float]]:
    numbers = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value or "")
    result: list[list[float]] = []
    for index in range(0, len(numbers) - 1, 2):
        result.append([float(numbers[index]), float(numbers[index + 1])])
    return result


def _linear_path_points(value: str, transform) -> list[list[float]] | None:
    """Transform only paths whose numbers are unambiguously M/L pairs.

    SVG arc and curve commands carry radii, flags, and control points. A
    generic numeric-pair regex turns those non-coordinate values into fake
    board points, which can make a renderer's bounds explode. Preserve those
    exact paths in ``pathRaw`` and leave sampling to the SVG-aware renderer.
    """

    if re.search(r"[AaCcHhQqSsTtVv]", value or ""):
        return None
    return [transform(point) for point in _parse_xy_pairs(value)]


def _track_points(value: str) -> list[list[float]]:
    numbers = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value or "")
    if len(numbers) % 2:
        raise ValueError(f"track has an odd coordinate count: {value!r}")
    return [[float(numbers[index]), float(numbers[index + 1])] for index in range(0, len(numbers), 2)]


def _parse_gerber_outline(path: Path) -> list[list[float]]:
    """Read the absolute 3.3 Gerber outline into millimetre points."""

    points: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"X(\d+)Y(\d+)D0([12])", line)
        if not match:
            continue
        x = int(match.group(1)) / 1000.0
        y = int(match.group(2)) / 1000.0
        point = [x, y]
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 3:
        raise ValueError(f"Gerber outline {path} did not contain at least three points")
    return points


def _transformer(raw_bounds: Mapping[str, float]):
    min_x = float(raw_bounds["minX"])
    max_y = float(raw_bounds["maxY"])

    def transform(point: Sequence[float]) -> list[float]:
        return [
            round((float(point[0]) - min_x) * RAW_UNITS_MM, 6),
            round((max_y - float(point[1])) * RAW_UNITS_MM, 6),
        ]

    return transform


def _layer(value: str | None) -> int | str | None:
    parsed = _integer(value)
    return parsed if parsed is not None else (value or None)


def _raw_records(shapes: Sequence[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expand LIB children while retaining wrappers and original order."""

    top: list[dict[str, Any]] = []
    expanded: list[dict[str, Any]] = []
    for index, raw in enumerate(shapes):
        if not isinstance(raw, str) or not raw:
            continue
        pieces = raw.split("#@$") if raw.startswith("LIB~") else [raw]
        if raw.startswith("LIB~"):
            wrapper = pieces[0]
            fields = wrapper.split("~")
            item = {"raw": wrapper, "kind": "LIB", "fields": fields, "topIndex": index, "childIndex": None}
            top.append(item)
            expanded.append(item)
            children = pieces[1:]
        else:
            fields = pieces[0].split("~")
            item = {"raw": pieces[0], "kind": fields[0], "fields": fields, "topIndex": index, "childIndex": 0}
            top.append(item)
            expanded.append(item)
            children = []
        for child_index, child in enumerate(children, start=1):
            if not child:
                continue
            child_fields = child.split("~")
            expanded.append({
                "raw": child,
                "kind": child_fields[0],
                "fields": child_fields,
                "topIndex": index,
                "childIndex": child_index,
                "componentId": fields[6] if len(fields) > 6 else None,
            })
    return top, expanded


def _path_record(
    record: Mapping[str, Any],
    transform,
    *,
    component_id: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    fields = record["fields"]
    kind = str(record["kind"])
    raw = str(record["raw"])
    graphic: dict[str, Any] = {
        "id": _id_for(fields, kind),
        "kind": kind.lower(),
        "sourceKind": kind,
        "layer": None,
        "net": None,
        "sourceRaw": raw,
    }
    if component_id:
        graphic["componentId"] = component_id
    if ref:
        graphic["ref"] = ref

    if kind == "TEXT":
        graphic.update({
            "kind": "text",
            "layer": _layer(fields[7] if len(fields) > 7 else None),
            "textType": fields[1] if len(fields) > 1 else None,
            "visible": not (len(fields) > 12 and fields[12] == "none"),
            "width": _mm_length(fields[4], 0),
            "xRaw": _number(fields[2]),
            "yRaw": _number(fields[3]),
            "x": transform([_number(fields[2], 0), _number(fields[3], 0)])[0],
            "y": transform([_number(fields[2], 0), _number(fields[3], 0)])[1],
            "rotation": _number(fields[5], 0),
            "text": fields[10] if len(fields) > 10 else "",
            # This is the original EasyEDA contour path, including every
            # C/A command and glyph contour.  Do not substitute browser text.
            "pathRaw": fields[11] if len(fields) > 11 else "",
            "font": fields[14] if len(fields) > 14 else None,
        })
        return graphic

    if kind in {"SOLIDREGION", "COPPERAREA"}:
        path_index = 3 if kind == "SOLIDREGION" else 4
        graphic.update({
            "kind": "solid-region" if kind == "SOLIDREGION" else "copper-area",
            # COPPERAREA starts with an internal type/version field; its
            # actual copper layer is field 2. SOLIDREGION uses field 1.
            "layer": _layer(fields[2] if kind == "COPPERAREA" and len(fields) > 2 else (fields[1] if len(fields) > 1 else None)),
            "net": fields[2] if kind == "SOLIDREGION" and len(fields) > 2 else (fields[3] if len(fields) > 3 else None),
            "pathRaw": fields[path_index] if len(fields) > path_index else "",
        })
        linear_points = _linear_path_points(graphic["pathRaw"], transform)
        if linear_points is not None:
            graphic["pointsMM"] = linear_points
        return graphic

    if kind == "TRACK":
        raw_points = _track_points(fields[4] if len(fields) > 4 else "")
        graphic.update({
            "kind": "silk-track" if _integer(fields[2]) in (3, 4) else "track-geometry",
            "layer": _layer(fields[2] if len(fields) > 2 else None),
            "net": fields[3] if len(fields) > 3 and fields[3] else None,
            "width": _mm_length(fields[1], 0),
            "widthRaw": _number(fields[1], 0),
            "pointsMM": [transform(point) for point in raw_points],
            "pointsRaw": raw_points,
        })
        return graphic

    if kind == "ARC":
        graphic.update({
            "kind": "arc",
            "layer": _layer(fields[2] if len(fields) > 2 else None),
            "net": fields[3] if len(fields) > 3 and fields[3] else None,
            "width": _mm_length(fields[1], 0),
            "widthRaw": _number(fields[1], 0),
            "pathRaw": fields[4] if len(fields) > 4 else "",
        })
        return graphic

    if kind == "RECT":
        x, y = _number(fields[1], 0), _number(fields[2], 0)
        width, height = _number(fields[3], 0), _number(fields[4], 0)
        corners = [[x, y], [x + width, y], [x + width, y + height], [x, y + height], [x, y]]
        graphic.update({
            "kind": "rect",
            "layer": _layer(fields[5] if len(fields) > 5 else None),
            "xRaw": x,
            "yRaw": y,
            "widthRaw": width,
            "heightRaw": height,
            "width": _mm_length(width, 0),
            "height": _mm_length(height, 0),
            "pointsMM": [transform(point) for point in corners],
            "net": fields[11] if len(fields) > 11 and fields[11] else None,
        })
        return graphic

    if kind == "CIRCLE":
        x, y = _number(fields[1], 0), _number(fields[2], 0)
        graphic.update({
            "kind": "circle",
            "layer": _layer(fields[5] if len(fields) > 5 else None),
            "xRaw": x,
            "yRaw": y,
            "x": transform([x, y])[0],
            "y": transform([x, y])[1],
            "diameter": _mm_length(fields[3]),
            "width": _mm_length(fields[4]),
            "diameterRaw": _number(fields[3]),
            "widthRaw": _number(fields[4]),
        })
        return graphic

    if kind == "HOLE":
        x, y = _number(fields[1], 0), _number(fields[2], 0)
        graphic.update({
            "kind": "hole",
            "xRaw": x,
            "yRaw": y,
            "x": transform([x, y])[0],
            "y": transform([x, y])[1],
            "diameter": _mm_length(fields[3]),
            "diameterRaw": _number(fields[3]),
        })
        return graphic

    if kind == "SVGNODE":
        node: Any
        try:
            node = json.loads(fields[1])
        except (IndexError, TypeError, ValueError, json.JSONDecodeError):
            node = None
        layer_value = node.get("layerid") if isinstance(node, dict) else None
        if layer_value is None and isinstance(node, dict):
            layer_value = node.get("attrs", {}).get("layerid")
        graphic.update({
            "kind": "svg-node",
            "layer": _layer(str(layer_value) if layer_value is not None else None),
            "nodeName": node.get("nodeName") if isinstance(node, dict) else None,
            "svg": node,
        })
        return graphic

    if kind == "DIMENSION":
        graphic.update({
            "kind": "dimension",
            "layer": _layer(fields[1] if len(fields) > 1 else None),
            "pathRaw": fields[2] if len(fields) > 2 else "",
        })
        return graphic

    # Keep any future/unknown source shape as a raw graphic.  This makes a
    # newly introduced EasyEDA primitive visible to tests and review rather
    # than silently discarding it during conversion.
    graphic["kind"] = kind.lower() or "unknown"
    return graphic


def _parse_pad(record: Mapping[str, Any], transform, component_id: str | None, ref: str | None) -> dict[str, Any]:
    p = record["fields"]
    x = _number(p[2], 0)
    y = _number(p[3], 0)
    # EasyEDA rounds the ordinary x/y fields to three decimals but keeps the
    # source placement in its final comma-separated center field. Prefer that
    # exact source coordinate when present, while retaining the rounded record
    # values for auditability.
    record_x, record_y = x, y
    if len(p) > 19 and "," in p[19]:
        center = p[19].split(",", 1)
        exact_x, exact_y = _number(center[0]), _number(center[1])
        if exact_x is not None and exact_y is not None:
            x, y = exact_x, exact_y
    result: dict[str, Any] = {
        "id": _id_for(p, "PAD"),
        "ref": ref,
        "number": p[8] if len(p) > 8 else "",
        "net": p[7] if len(p) > 7 and p[7] else None,
        "x": transform([x, y])[0],
        "y": transform([x, y])[1],
        "xRaw": x,
        "yRaw": y,
        "recordXRaw": record_x,
        "recordYRaw": record_y,
        "width": _mm_length(p[4], 0),
        "height": _mm_length(p[5], 0),
        "widthRaw": _number(p[4], 0),
        "heightRaw": _number(p[5], 0),
        "shape": p[1] if len(p) > 1 else "",
        "rotation": _number(p[11], 0),
        "drill": 2 * (_mm_length(p[9]) or 0) if len(p) > 9 else None,
        "drillRaw": _number(p[9]) if len(p) > 9 else None,
        "layer": _layer(p[6] if len(p) > 6 else None),
        "sourceRaw": record["raw"],
    }
    if component_id:
        result["componentId"] = component_id
    # These fields distinguish plated, hole and layer details without asking
    # the renderer to reinterpret the positional source record.
    if len(p) > 15:
        result["plated"] = p[15] or None
    if len(p) > 18:
        result["holeDiameter"] = _mm_length(p[18])
        result["holeDiameterRaw"] = _number(p[18])
    if len(p) > 19:
        result["centerRaw"] = p[19] or None
    return result


def _parse_track(record: Mapping[str, Any], transform) -> dict[str, Any]:
    p = record["fields"]
    raw_points = _track_points(p[4] if len(p) > 4 else "")
    return {
        "id": _id_for(p, "TRACK"),
        "layer": _layer(p[2] if len(p) > 2 else None),
        "net": p[3] if len(p) > 3 and p[3] else None,
        "width": _mm_length(p[1], 0),
        "widthRaw": _number(p[1], 0),
        "points": [transform(point) for point in raw_points],
        "pointsRaw": raw_points,
        "sourceRaw": record["raw"],
    }


def _parse_via(record: Mapping[str, Any], transform) -> dict[str, Any]:
    p = record["fields"]
    x = _number(p[1], 0)
    y = _number(p[2], 0)
    return {
        "id": _id_for(p, "VIA"),
        "x": transform([x, y])[0],
        "y": transform([x, y])[1],
        "xRaw": x,
        "yRaw": y,
        "diameter": _mm_length(p[3], 0),
        "drill": 2 * (_mm_length(p[5]) or 0),
        "diameterRaw": _number(p[3], 0),
        "drillRaw": _number(p[5]),
        "net": p[4] if len(p) > 4 and p[4] else None,
        "sourceRaw": record["raw"],
    }


def _parse_lib(record: Mapping[str, Any], children: Sequence[Mapping[str, Any]], transform) -> dict[str, Any]:
    p = record["fields"]
    component_id = _id_for(p, "LIB") if len(p) <= 6 or not p[6] else p[6]
    package = p[3].split("package`", 1)[1].split("`", 1)[0] if len(p) > 3 and "package`" in p[3] else ""
    texts = [child["fields"] for child in children if child["kind"] == "TEXT" and len(child["fields"]) > 10]
    source_ref = next((parts[10] for parts in texts if parts[1] == "P"), "")
    value = next((parts[10] for parts in texts if parts[1] == "N"), "")
    # The public source labels the LQFP footprint ``F103ZET6`` while the
    # schematic/provenance identifies that same 144-pad device as U2.  Keep
    # the source annotation and expose the stable engineering reference used
    # by the renderer/tests.
    ref = "U2" if value == "STM32F103ZET6" and package.startswith("LQFP-144") else source_ref
    x = _number(p[1], 0)
    y = _number(p[2], 0)
    pad_ids = [_id_for(child["fields"], "PAD") for child in children if child["kind"] == "PAD"]
    return {
        "id": component_id,
        "ref": ref,
        "sourceRef": source_ref,
        "value": value,
        "package": package,
        "x": transform([x, y])[0],
        "y": transform([x, y])[1],
        "xRaw": x,
        "yRaw": y,
        "rotation": _number(p[4], 0),
        "padIds": pad_ids,
        "sourceRaw": record["raw"],
    }


def _group_children(expanded: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in expanded:
        component_id = record.get("componentId")
        if component_id:
            groups.setdefault(str(component_id), []).append(record)
    return groups


def parse_board(source_path: Path = DEFAULT_SOURCE, gerber_path: Path = DEFAULT_GERBER) -> dict[str, Any]:
    """Parse the authoritative EasyEDA source and return OpenBoardData."""

    source_path = Path(source_path)
    gerber_path = Path(gerber_path)
    document = json.loads(source_path.read_text(encoding="utf-8"))
    result = document["result"]
    data = result["dataStr"]
    shapes = data["shape"]
    top, expanded = _raw_records(shapes)
    top_counts = Counter(record["kind"] for record in top)
    expanded_counts = Counter(record["kind"] for record in expanded)

    # The two layer-10 records are the source outline.  The second is the
    # closed rectangle; the first closes its lower-left edge around the USB
    # corner.  Use their combined extrema, and keep their full records below.
    outline_records = [
        record for record in expanded
        if record["kind"] == "TRACK"
        and _integer(record["fields"][2] if len(record["fields"]) > 2 else None) == 10
    ]
    if not outline_records:
        raise ValueError("source PCB did not contain layer-10 board outline tracks")
    outline_raw_points = [
        point
        for record in outline_records
        for point in _track_points(record["fields"][4])
    ]
    min_x = min(point[0] for point in outline_raw_points)
    max_x = max(point[0] for point in outline_raw_points)
    min_y = min(point[1] for point in outline_raw_points)
    max_y = max(point[1] for point in outline_raw_points)
    raw_bounds = {"minX": min_x, "maxX": max_x, "minY": min_y, "maxY": max_y}
    transform = _transformer(raw_bounds)
    gerber_outline = _parse_gerber_outline(gerber_path)

    # The outline is deliberately normalized to the lower-left Gerber frame.
    # The source outline contains two collinear pieces at the lower-left edge,
    # so a clean closed rectangle is the stable public outline contract.
    outline_mm = [
        [0.0, round((max_y - min_y) * RAW_UNITS_MM, 6)],
        [round((max_x - min_x) * RAW_UNITS_MM, 6), round((max_y - min_y) * RAW_UNITS_MM, 6)],
        [round((max_x - min_x) * RAW_UNITS_MM, 6), 0.0],
        [0.0, 0.0],
        [0.0, round((max_y - min_y) * RAW_UNITS_MM, 6)],
    ]

    groups = _group_children(expanded)
    lib_records = [record for record in top if record["kind"] == "LIB"]
    components: list[dict[str, Any]] = []
    component_by_id: dict[str, dict[str, Any]] = {}
    for record in lib_records:
        component_id = record["fields"][6] if len(record["fields"]) > 6 and record["fields"][6] else _id_for(record["fields"], "LIB")
        component = _parse_lib(record, groups.get(component_id, []), transform)
        components.append(component)
        component_by_id[component_id] = component
    ref_by_component = {key: value["ref"] for key, value in component_by_id.items()}

    pads: list[dict[str, Any]] = []
    tracks: list[dict[str, Any]] = []
    vias: list[dict[str, Any]] = []
    graphics: list[dict[str, Any]] = []
    for record in expanded:
        kind = record["kind"]
        component_id = record.get("componentId")
        ref = ref_by_component.get(component_id)
        if kind == "LIB":
            continue
        if kind == "PAD":
            pads.append(_parse_pad(record, transform, component_id, ref))
            continue
        if kind == "TRACK":
            # Top-level TRACK records are board routes/silk/outline.  TRACK
            # children inside a LIB are package artwork, so they belong in
            # graphics while retaining their exact source geometry there.
            # Keeping the public tracks list at the source top-level count
            # avoids presenting footprint artwork as electrical connectivity.
            if record.get("childIndex") == 0:
                tracks.append(_parse_track(record, transform))
            # Silk, outline, and all LIB artwork are also graphics, so
            # renderer clients can toggle the exact source drawing without
            # conflating it with selectable copper connectivity.
            layer = _integer(record["fields"][2] if len(record["fields"]) > 2 else None)
            if record.get("childIndex") != 0 or layer in (3, 4, 10):
                graphics.append(_path_record(record, transform, component_id=component_id, ref=ref))
            continue
        if kind == "VIA":
            vias.append(_parse_via(record, transform))
            continue
        graphics.append(_path_record(record, transform, component_id=component_id, ref=ref))

    for component in components:
        component["padIds"] = [pad["id"] for pad in pads if pad.get("componentId") == component["id"]]

    gerber_width = max(point[0] for point in gerber_outline) - min(point[0] for point in gerber_outline)
    gerber_height = max(point[1] for point in gerber_outline) - min(point[1] for point in gerber_outline)
    output_counts = {
        "components": len(components),
        "pads": len(pads),
        "tracks": len(tracks),
        "vias": len(vias),
        "graphics": len(graphics),
    }
    output_counts.update({
        "padsByRef": dict(Counter(pad["ref"] for pad in pads)),
        "tracksByLayer": dict(Counter(str(track["layer"]) for track in tracks)),
        "graphicsByKind": dict(Counter(graphic["kind"] for graphic in graphics)),
    })
    source_counts = {
        "topLevelShapeCount": len(top),
        "expandedShapeCount": len(expanded),
        "topLevel": dict(top_counts),
        "expanded": dict(expanded_counts),
        "topLevelTrackCount": top_counts["TRACK"],
        "topLevelViaCount": top_counts["VIA"],
        "topLevelLibCount": top_counts["LIB"],
        "topLevelPadCount": top_counts["PAD"],
        "expandedTrackCount": expanded_counts["TRACK"],
        "expandedViaCount": expanded_counts["VIA"],
        "expandedPadCount": expanded_counts["PAD"],
        "expandedTextCount": expanded_counts["TEXT"],
        "expandedCopperAreaCount": expanded_counts["COPPERAREA"],
        "expandedSolidRegionCount": expanded_counts["SOLIDREGION"],
        "expandedSilkTrackCount": sum(
            1 for record in expanded
            if record["kind"] == "TRACK" and _integer(record["fields"][2] if len(record["fields"]) > 2 else None) in (3, 4)
        ),
    }

    board_width = round((max_x - min_x) * RAW_UNITS_MM, 6)
    board_height = round((max_y - min_y) * RAW_UNITS_MM, 6)
    output: dict[str, Any] = {
        "meta": {
            "author": "PE.JADO",
            "sourceUrl": "https://oshwhub.com/PE.JADO/stm32f103zet6",
            "license": "GPL-3.0-only",
            "widthMm": 56.098,
            "heightMm": 53.5,
            "originRaw": [
                _number(data.get("head", {}).get("x"), 4020),
                _number(data.get("head", {}).get("y"), 3272),
            ],
            "unitsMmPerRaw": RAW_UNITS_MM,
            "sourceDocument": _display_path(source_path),
            "sourceSha256": _sha256(source_path),
            "gerberOutline": {
                "sourceFile": _display_path(gerber_path),
                "widthMm": round(gerber_width, 6),
                "heightMm": round(gerber_height, 6),
                "pointsMM": gerber_outline,
                "sha256": _sha256(gerber_path),
            },
            "coordinateTransform": {
                "rawBounds": raw_bounds,
                "rawOrigin": [min_x, max_y],
                "scale": [RAW_UNITS_MM, RAW_UNITS_MM],
                "yAxis": "inverted (EasyEDA down to Gerber up)",
                "boardWidthFromSourceMm": board_width,
                "boardHeightFromSourceMm": board_height,
            },
        },
        "outlineMM": outline_mm,
        "outlineRaw": [
            {
                "id": _id_for(record["fields"], "TRACK"),
                "layer": _layer(record["fields"][2] if len(record["fields"]) > 2 else None),
                "points": _track_points(record["fields"][4]),
                "sourceRaw": record["raw"],
            }
            for record in outline_records
        ],
        "tracks": tracks,
        "vias": vias,
        "pads": pads,
        "components": components,
        "graphics": graphics,
        "sourceCounts": source_counts,
        "outputCounts": output_counts,
        "sourceFacts": {
            "mainMcu": {
                "ref": "U2",
                "package": "LQFP-144_L20.0-W20.0-P0.50-LS22.0-BL",
                "padCount": len(component_by_id.get(next((key for key, value in component_by_id.items() if value["ref"] == "U2"), ""), {}).get("padIds", [])),
            },
            "headers": {
                ref: len(component["padIds"])
                for component in components
                for ref in [component["ref"]]
                if ref.startswith("H")
            },
            "headerContactCount": sum(
                len(component["padIds"])
                for component in components
                if component["ref"].startswith("H")
            ),
            "boot": {
                "ref": "BOOT",
                "padCount": next((len(component["padIds"]) for component in components if component["ref"] == "BOOT"), 0),
            },
            "led1": {
                "ref": "LED1",
                "value": next((component["value"] for component in components if component["ref"] == "LED1"), ""),
                "package": next((component["package"] for component in components if component["ref"] == "LED1"), ""),
                "sourceFact": "3V3 -> LED1 -> R1 1k -> GND; this source has no PB5/PE5 onboard LED",
            },
        },
    }
    return output


def _umd_source(data: Mapping[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2, separators=(",", ": "))
    return """/* Generated by tools/import_open_board.py; source geometry is preserved in sourceRaw/pathRaw. */\n""" \
        + "(function (root, factory) {\n" \
        + "  if (typeof module === 'object' && module.exports) module.exports = factory();\n" \
        + "  else if (root) root.OpenBoardData = factory();\n" \
        + "})(typeof globalThis !== 'undefined' ? globalThis : this, function () {\n" \
        + f"  return {payload};\n" \
        + "});\n"


def write_output(data: Mapping[str, Any], output_path: Path = DEFAULT_OUTPUT) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_umd_source(data), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true", help="print counts after conversion")
    args = parser.parse_args(argv)
    data = parse_board(args.source, args.gerber)
    write_output(data, args.output)
    if args.summary:
        print(json.dumps({"sourceCounts": data["sourceCounts"], "outputCounts": data["outputCounts"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
