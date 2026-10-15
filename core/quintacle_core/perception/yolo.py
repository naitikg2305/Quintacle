"""Object tags via YOLOX-nano ONNX (80 COCO classes), run on onnxruntime CPU.

Why YOLOX-nano and not ultralytics/yolov8: the ultralytics stack drags in
torch+torchvision (GB-scale install; facenet-pytorch's pinned torch doesn't
even resolve on Python 3.14), while YOLOX publishes an official ~3.5 MB ONNX
asset that runs anywhere onnxruntime does — including, later, a phone.
Decode logic (grid offsets + exp-scaled sizes per stride, then NMS) follows
Megvii's own onnx demo, reimplemented in numpy so there's no cv2 dependency.

All heavy imports are lazy — this module is only imported from inside
perceive_photo once deps are known to be present.
"""

from __future__ import annotations

from PIL import Image

from .download import YOLO_MODEL, ensure_model

_INPUT_SIZE = 416  # yolox_nano's export size
_STRIDES = (8, 16, 32)
_CONF_THRESHOLD = 0.35  # obj*cls score below this isn't worth a tag
_NMS_THRESHOLD = 0.45

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
)

_session = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3
        _session = ort.InferenceSession(
            str(ensure_model(YOLO_MODEL)), sess_options=options, providers=["CPUExecutionProvider"]
        )
    return _session


def _preprocess(img: Image.Image):
    """YOLOX convention: aspect-preserving resize into a 114-grey canvas, BGR
    channel order, raw 0-255 floats (no mean/std), NCHW."""
    import numpy as np

    rgb = img.convert("RGB")
    ratio = min(_INPUT_SIZE / rgb.height, _INPUT_SIZE / rgb.width)
    new_w, new_h = max(1, round(rgb.width * ratio)), max(1, round(rgb.height * ratio))
    resized = np.asarray(rgb.resize((new_w, new_h), Image.BILINEAR), dtype=np.float32)
    canvas = np.full((_INPUT_SIZE, _INPUT_SIZE, 3), 114.0, dtype=np.float32)
    canvas[:new_h, :new_w] = resized[:, :, ::-1]  # RGB -> BGR
    blob = canvas.transpose(2, 0, 1)[None]
    return blob, ratio


def _decode(outputs):
    """Map raw per-cell predictions back to pixel space: xy are cell offsets
    (+grid, *stride), wh are log-space (*exp, *stride)."""
    import numpy as np

    grids, strides = [], []
    for stride in _STRIDES:
        size = _INPUT_SIZE // stride
        xv, yv = np.meshgrid(np.arange(size), np.arange(size))
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((size * size, 1), stride))
    grid = np.concatenate(grids, axis=0).astype(np.float32)
    stride = np.concatenate(strides, axis=0).astype(np.float32)
    outputs[..., :2] = (outputs[..., :2] + grid) * stride
    outputs[..., 2:4] = np.exp(outputs[..., 2:4]) * stride
    return outputs


def nms(boxes, scores, threshold: float):
    """Plain greedy IoU NMS over xyxy boxes (numpy, no cv2). Shared with the
    face detector."""
    import numpy as np

    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / np.maximum(area_i + area_r - inter, 1e-9)
        order = rest[iou <= threshold]
    return keep


def detect_tags(img: Image.Image) -> list[str]:
    """Deduped COCO labels present in the photo, ordered by detection
    confidence (best first)."""
    import numpy as np

    session = _get_session()
    blob, ratio = _preprocess(img)
    raw = session.run(None, {session.get_inputs()[0].name: blob})[0]
    preds = _decode(raw[0])  # (N, 85): cx, cy, w, h, obj, 80 cls

    scores_all = preds[:, 4:5] * preds[:, 5:]
    cls_ids = scores_all.argmax(1)
    cls_scores = scores_all[np.arange(len(cls_ids)), cls_ids]
    mask = cls_scores >= _CONF_THRESHOLD
    if not mask.any():
        return []
    boxes_cxcywh = preds[mask, :4] / ratio
    boxes = np.empty_like(boxes_cxcywh)
    boxes[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
    boxes[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
    boxes[:, 2] = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2
    boxes[:, 3] = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2
    cls_ids, cls_scores = cls_ids[mask], cls_scores[mask]

    best_per_label: dict[str, float] = {}
    for class_id in np.unique(cls_ids):
        sel = cls_ids == class_id
        kept = nms(boxes[sel], cls_scores[sel], _NMS_THRESHOLD)
        if kept:
            label = COCO_CLASSES[int(class_id)]
            best_per_label[label] = float(cls_scores[sel][kept].max())
    return sorted(best_per_label, key=best_per_label.get, reverse=True)
