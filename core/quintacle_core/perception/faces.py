"""Face detection + embeddings: SCRFD-500M (boxes + 5 landmarks) feeding a
MobileFaceNet ArcFace recognizer (512-d), both ONNX from insightface's
official buffalo_sc pack — the same detect->align->embed->cosine shape as the
user's PeopleLens prototype (MTCNN+FaceNet), swapped onto onnxruntime because
facenet-pytorch's pinned torch doesn't install on Python 3.14 and torch is
GB-heavy anyway.

Decode follows insightface's scrfd.py (per-stride score/bbox[/kps] heads,
distances * stride, 2 anchors per cell); alignment is the standard ArcFace
5-point similarity transform (Umeyama), warped with PIL instead of
cv2.warpAffine so cv2 stays optional.

Heavy imports are lazy — only reached from perceive_photo after the dep check.
"""

from __future__ import annotations

from PIL import Image

from .download import FACE_DETECT_MODEL, FACE_EMBED_MODEL, ensure_model

_DET_INPUT_SIZE = 640
_DET_STRIDES = (8, 16, 32)
_NUM_ANCHORS = 2
_DET_SCORE_THRESHOLD = 0.5
_DET_NMS_THRESHOLD = 0.4
_EMBED_SIZE = 112

# ArcFace's canonical 5-landmark template on a 112x112 crop
# (left eye, right eye, nose, left mouth corner, right mouth corner).
_ARCFACE_TEMPLATE = (
    (38.2946, 51.6963),
    (73.5318, 51.5014),
    (56.0252, 71.7366),
    (41.5493, 92.3655),
    (70.7299, 92.2041),
)

_sessions: dict[str, object] = {}


def _get_session(model_name: str):
    if model_name not in _sessions:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3
        _sessions[model_name] = ort.InferenceSession(
            str(ensure_model(model_name)), sess_options=options, providers=["CPUExecutionProvider"]
        )
    return _sessions[model_name]


def _detect(img: Image.Image):
    """Run SCRFD; returns (boxes_xyxy, landmarks (N,5,2)) in original-image
    pixel coordinates."""
    import numpy as np

    from .yolo import nms

    session = _get_session(FACE_DETECT_MODEL)
    rgb = img.convert("RGB")
    ratio = min(_DET_INPUT_SIZE / rgb.height, _DET_INPUT_SIZE / rgb.width)
    new_w, new_h = max(1, round(rgb.width * ratio)), max(1, round(rgb.height * ratio))
    canvas = np.zeros((_DET_INPUT_SIZE, _DET_INPUT_SIZE, 3), dtype=np.float32)
    canvas[:new_h, :new_w] = np.asarray(rgb.resize((new_w, new_h), Image.BILINEAR), dtype=np.float32)
    blob = ((canvas - 127.5) / 128.0).transpose(2, 0, 1)[None]

    outputs = session.run(None, {session.get_inputs()[0].name: blob})
    levels = len(_DET_STRIDES)
    with_kps = len(outputs) == levels * 3  # 3 heads per stride: score, bbox, kps

    all_boxes, all_scores, all_kps = [], [], []
    for idx, stride in enumerate(_DET_STRIDES):
        scores = outputs[idx].reshape(-1)
        bbox_preds = outputs[idx + levels].reshape(-1, 4) * stride
        size = _DET_INPUT_SIZE // stride
        xv, yv = np.meshgrid(np.arange(size), np.arange(size))
        centers = np.stack((xv, yv), axis=-1).reshape(-1, 2).astype(np.float32) * stride
        centers = np.repeat(centers, _NUM_ANCHORS, axis=0)  # 2 anchors per cell
        keep = scores >= _DET_SCORE_THRESHOLD
        if not keep.any():
            continue
        centers_k, bbox_k = centers[keep], bbox_preds[keep]
        boxes = np.stack(
            (
                centers_k[:, 0] - bbox_k[:, 0],
                centers_k[:, 1] - bbox_k[:, 1],
                centers_k[:, 0] + bbox_k[:, 2],
                centers_k[:, 1] + bbox_k[:, 3],
            ),
            axis=-1,
        )
        all_boxes.append(boxes)
        all_scores.append(scores[keep])
        if with_kps:
            kps_preds = outputs[idx + levels * 2].reshape(-1, 5, 2)[keep] * stride
            all_kps.append(centers_k[:, None, :] + kps_preds)

    if not all_boxes:
        return np.empty((0, 4), dtype=np.float32), np.empty((0, 5, 2), dtype=np.float32)

    boxes = np.concatenate(all_boxes) / ratio
    scores = np.concatenate(all_scores)
    kps = (np.concatenate(all_kps) / ratio) if with_kps else np.zeros((len(boxes), 5, 2), dtype=np.float32)
    kept = nms(boxes, scores, _DET_NMS_THRESHOLD)
    return boxes[kept], kps[kept]


def _similarity_transform(src, dst):
    """Umeyama similarity transform (rotation+scale+translation, no shear)
    mapping src points onto dst — the cv2.estimateAffinePartial2D-free way to
    get ArcFace's canonical alignment. Returns a 2x3 matrix M with
    dst ~= M @ [src, 1]."""
    import numpy as np

    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n = src.shape[0]
    src_mean, dst_mean = src.mean(0), dst.mean(0)
    src_d, dst_d = src - src_mean, dst - dst_mean
    cov = dst_d.T @ src_d / n
    u, s, vt = np.linalg.svd(cov)
    d = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1] = -1
    rotation = u @ np.diag(d) @ vt
    var_src = (src_d**2).sum() / n
    scale = (s * d).sum() / var_src if var_src > 0 else 1.0
    translation = dst_mean - scale * rotation @ src_mean
    return np.hstack([scale * rotation, translation[:, None]])


def _align(img: Image.Image, landmarks) -> Image.Image:
    """Warp the face to the 112x112 ArcFace template. PIL's AFFINE transform
    wants the INVERSE mapping (output pixel -> input pixel), so invert M."""
    import numpy as np

    matrix = _similarity_transform(landmarks, _ARCFACE_TEMPLATE)
    full = np.vstack([matrix, [0.0, 0.0, 1.0]])
    inverse = np.linalg.inv(full)
    coeffs = inverse[:2].reshape(-1)
    return img.convert("RGB").transform(
        (_EMBED_SIZE, _EMBED_SIZE), Image.AFFINE, tuple(coeffs), resample=Image.BILINEAR
    )


def _embed(face_crop: Image.Image) -> list[float]:
    import numpy as np

    session = _get_session(FACE_EMBED_MODEL)
    arr = np.asarray(face_crop, dtype=np.float32)
    blob = ((arr - 127.5) / 127.5).transpose(2, 0, 1)[None]
    vector = session.run(None, {session.get_inputs()[0].name: blob})[0][0]
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise ValueError("face recognizer produced a zero embedding")
    return [float(v) for v in vector / norm]


def detect_faces(img: Image.Image) -> list[dict]:
    """All faces in the photo as
    {"box": [x, y, w, h] (0-1 of image size), "vector": 512 floats (L2-normed)}.
    Faces whose landmarks are unusable fall back to an expanded bbox crop —
    worse embedding, still better than dropping the observation."""
    boxes, landmarks = _detect(img)
    width, height = img.width, img.height
    faces: list[dict] = []
    for box, kps in zip(boxes, landmarks):
        x1, y1, x2, y2 = (float(v) for v in box)
        if (kps != 0).any():
            crop = _align(img, kps)
        else:
            margin_x, margin_y = 0.1 * (x2 - x1), 0.1 * (y2 - y1)
            crop = (
                img.convert("RGB")
                .crop((max(0, x1 - margin_x), max(0, y1 - margin_y), min(width, x2 + margin_x), min(height, y2 + margin_y)))
                .resize((_EMBED_SIZE, _EMBED_SIZE), Image.BILINEAR)
            )
        x1c, y1c = max(0.0, x1), max(0.0, y1)
        x2c, y2c = min(float(width), x2), min(float(height), y2)
        faces.append(
            {
                "box": [
                    round(x1c / width, 4),
                    round(y1c / height, 4),
                    round((x2c - x1c) / width, 4),
                    round((y2c - y1c) / height, 4),
                ],
                "vector": _embed(crop),
            }
        )
    return faces
