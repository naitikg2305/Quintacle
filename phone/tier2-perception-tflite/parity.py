#!/usr/bin/env python
"""ONNX vs TFLite parity harness — the proof that the phone's perception lane
computes the same things the desktop does, without needing a phone.

Runs the FULL perceive_photo() pipeline (not isolated model calls) over the
same real photos under three backends in one process:

    onnx          the shipping desktop path (baseline)
    tflite f32    float32 TFLite — conversion-correctness check (>0.98 cosine)
    tflite drq    dynamic-range-quant TFLite — the phone target; drift report

and reports, per photo: YOLO tag-set agreement, face-count + box IoU, and the
embedding cosine between the ONNX face and the TFLite face of the same photo.

Cross-backend enrollment (the sync story's hinge): one face is enrolled from
an ONNX observation — as if enrolled on the desktop — and every TFLite pass
then matches against it through the real storage.best_match path, answering:
does a face enrolled via ONNX on desktop still clear FACE_MATCH_THRESHOLD
(0.55) when observed via TFLite on the phone?

Run in the BASE venv (Python 3.14 — core/.venv needs perception deps plus
`pip install ai-edge-litert`), after convert.py has produced the models:

    core/.venv/bin/python phone/tier2-perception-tflite/parity.py

Photos are read-only inputs; all perception state (embeddings, profiles) goes
to a throwaway temp dir. Pass photo paths as args to override the defaults.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

# Face photos (same person across the set — known to detect) + object-y shots.
FACE_PHOTO_DIR = Path("/home/naitikg/Desktop/Notebook/Multimedia/Photos/Beard stages")
OBJECT_PHOTOS = [
    Path("/home/naitikg/Downloads/20260908_203808.jpg"),
    Path("/home/naitikg/Downloads/20260915_140200.jpg"),
    Path("/home/naitikg/Downloads/20260916_104104.jpg"),
]

BACKENDS = (
    ("onnx", {"QUINTACLE_PERCEPTION_BACKEND": "onnx"}),
    ("tflite-f32", {"QUINTACLE_PERCEPTION_BACKEND": "tflite", "QUINTACLE_TFLITE_VARIANT": "float32"}),
    ("tflite-drq", {"QUINTACLE_PERCEPTION_BACKEND": "tflite", "QUINTACLE_TFLITE_VARIANT": "dynamic_range_quant"}),
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


def iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, aw, ah = box_a
    bx1, by1, bw, bh = box_b
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def match_faces(ref: list, other: list) -> list[tuple[int, int, float]]:
    """Greedy best-IoU pairing of two face lists -> [(ref_idx, other_idx, iou)]."""
    pairs = sorted(
        ((i, j, iou(ref[i]["box"], other[j]["box"])) for i in range(len(ref)) for j in range(len(other))),
        key=lambda t: -t[2],
    )
    used_i, used_j, out = set(), set(), []
    for i, j, score in pairs:
        if i in used_i or j in used_j or score <= 0.0:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((i, j, score))
    return out


def run_pass(perception, storage, photos: list[Path], label: str) -> dict:
    """One backend pass over all photos. Returns {photo: {tags, faces, ms}}
    where each face is {box, vector, match}."""
    results: dict[Path, dict] = {}
    for photo in photos:
        data = photo.read_bytes()
        start = time.perf_counter()
        result = perception.perceive_photo(data, "image/jpeg")
        elapsed = (time.perf_counter() - start) * 1000
        if result is None:
            raise SystemExit(
                f"[{label}] perceive_photo returned None for {photo.name} — backend unavailable; "
                "did convert.py run, and is ai-edge-litert installed in core/.venv?"
            )
        faces = []
        for face in result.faces:
            stored = storage.load_embedding(face.embedding_id)
            faces.append({"box": face.box, "vector": stored["vector"], "match": face.match})
        results[photo] = {"tags": result.tags, "faces": faces, "ms": elapsed}
    return results


def largest_face_index(faces: list) -> int | None:
    if not faces:
        return None
    return max(range(len(faces)), key=lambda i: faces[i]["box"][2] * faces[i]["box"][3])


def main() -> int:
    photos = [Path(p) for p in sys.argv[1:]]
    if not photos:
        photos = sorted(FACE_PHOTO_DIR.glob("*.jpg")) + [p for p in OBJECT_PHOTOS if p.is_file()]
    missing = [p for p in photos if not p.is_file()]
    if missing:
        raise SystemExit(f"missing photos: {missing}")

    # isolated perception state; real (shared) model weights
    models = os.environ.get(
        "QUINTACLE_PERCEPTION_MODELS_DIR",
        str(Path.home() / ".quintacle" / "perception" / "models"),
    )
    tmp = tempfile.mkdtemp(prefix="quintacle-parity-")
    os.environ["QUINTACLE_DATA_DIR"] = tmp
    os.environ["QUINTACLE_PERCEPTION_MODELS_DIR"] = models

    from quintacle_core import perception
    from quintacle_core.perception import FACE_MATCH_THRESHOLD, storage

    face_photos = [p for p in photos if p.parent == FACE_PHOTO_DIR]
    enroll_photo = face_photos[0] if face_photos else None

    passes: dict[str, dict] = {}
    for label, env in BACKENDS:
        os.environ.update(env)
        passes[label] = run_pass(perception, storage, photos, label)
        # Cross-backend enrollment: right after the ONNX (desktop) pass,
        # enroll the subject's face from its first photo. Every later TFLite
        # pass then matches against this ONNX-born embedding via the real
        # storage.best_match path.
        if label == "onnx" and enroll_photo is not None:
            onnx_faces = passes["onnx"][enroll_photo]["faces"]
            idx = largest_face_index(onnx_faces)
            if idx is None:
                raise SystemExit(f"no face found in enrollment photo {enroll_photo.name}")
            # re-save the exact vector to get an id we control, then enroll
            vec = onnx_faces[idx]["vector"]
            eid = storage.save_embedding(vec, {"mime": "image/jpeg", "sha256": "parity-enroll"})
            perception.enroll_face(eid, "Subject")
            enrolled_vector = vec
    os.environ["QUINTACLE_PERCEPTION_BACKEND"] = "onnx"

    # ---- per-photo table ----
    header = (
        f"{'photo':<22} {'tags onnx==f32':<15} {'tags onnx==drq':<15} "
        f"{'faces o/f/d':<12} {'IoU f32':<8} {'IoU drq':<8} {'cos f32':<8} {'cos drq':<8} "
        f"{'xmatch f32':<16} {'xmatch drq':<16}"
    )
    print("\n=== PARITY TABLE (per photo; cos = ONNX-face vs TFLite-face embedding cosine;")
    print(f"    xmatch = TFLite face matched against the ONNX-enrolled 'Subject' @ threshold {FACE_MATCH_THRESHOLD}) ===")
    print(header)
    print("-" * len(header))

    cos_f32_all, cos_drq_all, iou_f32_all, iou_drq_all = [], [], [], []
    xmatch_rows = {"tflite-f32": [], "tflite-drq": []}
    tag_mismatches = []

    for photo in photos:
        o = passes["onnx"][photo]
        f = passes["tflite-f32"][photo]
        d = passes["tflite-drq"][photo]

        tags_f = "yes" if set(o["tags"]) == set(f["tags"]) else "NO"
        tags_d = "yes" if set(o["tags"]) == set(d["tags"]) else "NO"
        for label, p in (("f32", f), ("drq", d)):
            if set(o["tags"]) != set(p["tags"]):
                tag_mismatches.append(f"  {photo.name} [{label}]: onnx={o['tags']} tflite={p['tags']}")

        def face_stats(other):
            pairs = match_faces(o["faces"], other["faces"])
            ious = [s for _, _, s in pairs]
            coss = [cosine(o["faces"][i]["vector"], other["faces"][j]["vector"]) for i, j, _ in pairs]
            return ious, coss

        iou_f, cos_f = face_stats(f)
        iou_d, cos_d = face_stats(d)
        cos_f32_all += cos_f
        cos_drq_all += cos_d
        iou_f32_all += iou_f
        iou_drq_all += iou_d

        def xmatch(p, is_enroll_photo):
            # enrollment photo matched against its own enrolled vector is
            # trivially informative too (same-photo, cross-backend)
            best = None
            for face in p["faces"]:
                if face["match"] and face["match"]["person_name"] == "Subject":
                    score = face["match"]["score"]
                    best = max(best, score) if best is not None else score
            if best is not None:
                return f"MATCH {best:.3f}"
            if not p["faces"]:
                return "no face"
            # unknown: show the best sub-threshold score against the enrollment
            raw = max(cosine(face["vector"], enrolled_vector) for face in p["faces"]) if enroll_photo else -1
            return f"unknown {raw:.3f}"

        is_face_photo = photo.parent == FACE_PHOTO_DIR
        xm_f = xmatch(f, photo == enroll_photo) if is_face_photo else "-"
        xm_d = xmatch(d, photo == enroll_photo) if is_face_photo else "-"
        if is_face_photo:
            xmatch_rows["tflite-f32"].append(xm_f)
            xmatch_rows["tflite-drq"].append(xm_d)

        fmt = lambda vals: f"{min(vals):.3f}" if vals else "-"
        print(
            f"{photo.name:<22} {tags_f:<15} {tags_d:<15} "
            f"{len(o['faces'])}/{len(f['faces'])}/{len(d['faces']):<10} "
            f"{fmt(iou_f):<8} {fmt(iou_d):<8} {fmt(cos_f):<8} {fmt(cos_d):<8} "
            f"{xm_f:<16} {xm_d:<16}"
        )

    if tag_mismatches:
        print("\ntag mismatches in detail:")
        for line in tag_mismatches:
            print(line)

    # ---- summary ----
    def stats(vals):
        return f"min {min(vals):.4f} / mean {sum(vals)/len(vals):.4f} (n={len(vals)})" if vals else "n/a"

    ms = {label: sum(r["ms"] for r in passes[label].values()) / len(photos) for label, _ in BACKENDS}
    print("\n=== SUMMARY ===")
    print(f"photos: {len(photos)} ({len(face_photos)} face, {len(photos)-len(face_photos)} object)")
    print(f"embedding cosine ONNX vs TFLite-f32:  {stats(cos_f32_all)}   [target > 0.98]")
    print(f"embedding cosine ONNX vs TFLite-drq:  {stats(cos_drq_all)}")
    print(f"face box IoU   ONNX vs TFLite-f32:  {stats(iou_f32_all)}")
    print(f"face box IoU   ONNX vs TFLite-drq:  {stats(iou_drq_all)}")
    for label in ("tflite-f32", "tflite-drq"):
        rows = xmatch_rows[label]
        matched = sum(1 for r in rows if r.startswith("MATCH"))
        print(
            f"cross-backend enrollment ({label} vs ONNX-enrolled face): "
            f"{matched}/{len(rows)} face photos matched 'Subject' @ {FACE_MATCH_THRESHOLD}"
        )
    print(f"mean perceive_photo ms/photo: " + ", ".join(f"{k}={v:.0f}" for k, v in ms.items()))

    ok = bool(cos_f32_all) and min(cos_f32_all) > 0.98
    print(f"\nfloat32 parity {'PASS' if ok else 'FAIL'} (cosine floor {'>' if ok else '<='} 0.98)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
