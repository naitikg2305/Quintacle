"use client";

import { useState } from "react";
import { FileText, Paperclip, PenLine, Upload, X } from "lucide-react";
import ScribblePad from "@/components/ScribblePad";
import { Button } from "@/components/ui/Button";

// The Drop page's file machinery, extracted for the chat scratchpad
// (next-wave §9 — chat absorbs drop): a primary file + as many additional
// attachments as you want (a multi-page note, several angles of the same
// thing), with image/video previews and the scribble pad. Every file still
// flows through the SAME multipart /drop call and the same commit-time asset
// attachment — this component only holds and previews them.

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];
const VIDEO_EXT = ["mp4", "webm", "mov", "m4v"];

// Bank/card statement files route deterministically by extension (§2b) — the
// backend parses them without any model call; PDFs need a "statement:" prefix.
export const STATEMENT_EXT = ["csv", "ofx", "qfx"];

export function extFor(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export type DropAttachments = ReturnType<typeof useDropAttachments>;

export function useDropAttachments() {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  // Beyond the primary `file` — every asset-carrying entry type keeps all of
  // them at save time (see lib/entries.ts commitDropEntries).
  const [extraPhotos, setExtraPhotos] = useState<File[]>([]);
  // Preview URLs are created/revoked in the handlers, 1:1 with extraPhotos —
  // no effect needed (and no setState-in-effect lint hit).
  const [extraPreviewUrls, setExtraPreviewUrls] = useState<string[]>([]);

  function clearExtras() {
    extraPreviewUrls.forEach((u) => URL.revokeObjectURL(u));
    setExtraPhotos([]);
    setExtraPreviewUrls([]);
  }

  function onFileChosen(f: File | null) {
    setFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(f && IMAGE_EXT.includes(extFor(f)) ? URL.createObjectURL(f) : null);
    if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
    setVideoPreviewUrl(f && VIDEO_EXT.includes(extFor(f)) ? URL.createObjectURL(f) : null);
    if (!f) clearExtras();
  }

  function addExtraPhoto(f: File | null) {
    if (!f) return;
    setExtraPhotos([...extraPhotos, f]);
    setExtraPreviewUrls([...extraPreviewUrls, URL.createObjectURL(f)]);
  }

  function removeExtraPhoto(i: number) {
    URL.revokeObjectURL(extraPreviewUrls[i]);
    setExtraPhotos(extraPhotos.filter((_, idx) => idx !== i));
    setExtraPreviewUrls(extraPreviewUrls.filter((_, idx) => idx !== i));
  }

  // The chat → scratchpad bridge: a photo discussed in the conversation (or a
  // generated image) joins the pending drop like any chosen file — primary
  // slot first, extra attachment after that.
  function addFile(f: File) {
    if (!file) onFileChosen(f);
    else addExtraPhoto(f);
  }

  return { file, previewUrl, videoPreviewUrl, extraPhotos, extraPreviewUrls, onFileChosen, addExtraPhoto, removeExtraPhoto, addFile };
}

// The tray itself — drag-and-drop zone, choose-file, scribble pad, previews,
// and the extras grid. Compact enough for the scratchpad column.
export function AttachmentTray({ att }: { att: DropAttachments }) {
  const { file, previewUrl, videoPreviewUrl, extraPhotos, extraPreviewUrls, onFileChosen, addExtraPhoto, removeExtraPhoto } = att;
  const [showScribble, setShowScribble] = useState(false);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFileChosen(dropped);
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="space-y-2 rounded-xl border-2 border-dashed border-line-strong bg-accent/[0.03] p-3 text-center"
      >
        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={previewUrl} alt="" className="mx-auto max-h-48 rounded-lg" />
        ) : videoPreviewUrl ? (
          <video src={videoPreviewUrl} controls className="mx-auto max-h-48 rounded-lg" />
        ) : file ? (
          <p className="flex items-center justify-center gap-2 text-sm">
            <FileText size={16} className="text-accent" /> {file.name}
          </p>
        ) : (
          <p className="text-xs text-muted">Drag a photo, video, PDF, DOCX or bank/card statement (CSV/OFX/QFX) here</p>
        )}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-3 py-1.5 text-xs transition-colors hover:border-accent/60 hover:bg-accent/10">
            <Upload size={13} /> Choose file
            <input
              type="file"
              accept="image/*,video/*,.pdf,.docx,.stl,.csv,.ofx,.qfx"
              capture="environment"
              onChange={(e) => {
                onFileChosen(e.target.files?.[0] ?? null);
                e.target.value = "";
              }}
              className="hidden"
            />
          </label>
          <Button size="sm" onClick={() => setShowScribble((v) => !v)}>
            <PenLine size={13} /> {showScribble ? "Hide scribble" : "Scribble"}
          </Button>
          {file && (
            <Button size="sm" variant="ghost" onClick={() => onFileChosen(null)}>
              <X size={13} /> Clear
            </Button>
          )}
        </div>
      </div>

      {file && extraPhotos.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {extraPhotos.map((f, i) =>
            IMAGE_EXT.includes(extFor(f)) ? (
              <div key={i} className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={extraPreviewUrls[i]} alt="" className="h-24 w-full rounded-lg border border-line object-cover" />
                <button
                  onClick={() => removeExtraPhoto(i)}
                  aria-label="Remove attachment"
                  className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div key={i} className="relative flex h-24 flex-col items-center justify-center gap-1 rounded-lg border border-line p-2 text-center">
                <Paperclip size={16} className="text-accent" />
                <span className="line-clamp-2 break-all text-[10px] text-muted">{f.name}</span>
                <button
                  onClick={() => removeExtraPhoto(i)}
                  aria-label="Remove attachment"
                  className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-danger"
                >
                  <X size={12} />
                </button>
              </div>
            )
          )}
        </div>
      )}

      {file && (
        <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-accent hover:underline">
          <Paperclip size={13} /> add another attachment — as many as you want
          <input
            type="file"
            accept="image/*,video/*,.pdf,.docx,.stl"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              addExtraPhoto(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
        </label>
      )}

      {showScribble && (
        <ScribblePad
          onUse={(f) => {
            onFileChosen(f);
            setShowScribble(false);
          }}
        />
      )}
    </div>
  );
}
