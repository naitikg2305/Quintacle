"use client";

import { useEffect, useMemo, useState } from "react";
import { kbAssetUrl, listPhotos, Photo } from "@/lib/api";
import ImageLightbox from "@/components/ImageLightbox";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];
const MONTH_ORDER = [
  "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
];

export default function GalleryPage() {
  const [photos, setPhotos] = useState<Photo[]>([]);

  useEffect(() => {
    listPhotos().then(setPhotos);
  }, []);

  const byYearMonth = useMemo(() => {
    const years = new Map<string, Map<string, Photo[]>>();
    for (const p of photos) {
      const parts = p.folder.split("/"); // media/photos/<year>/<month>/...
      const year = parts[2] ?? "unknown";
      const month = parts[3] ?? "unknown";
      if (!years.has(year)) years.set(year, new Map());
      const months = years.get(year)!;
      if (!months.has(month)) months.set(month, []);
      months.get(month)!.push(p);
    }
    return years;
  }, [photos]);

  const years = Array.from(byYearMonth.keys()).sort().reverse();

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold">Gallery</h1>
        <p className="text-sm opacity-60 -mt-1">
          Every real photo, placed by its own EXIF date — {photos.length} photo{photos.length === 1 ? "" : "s"} so far.
        </p>
      </div>

      {years.length === 0 && <p className="text-sm opacity-60">Nothing here yet — drop a photo and it'll land here automatically.</p>}

      {years.map((year) => {
        const months = byYearMonth.get(year)!;
        const monthKeys = Array.from(months.keys()).sort(
          (a, b) => MONTH_ORDER.indexOf(a.toLowerCase()) - MONTH_ORDER.indexOf(b.toLowerCase())
        ).reverse();
        return (
          <div key={year} className="space-y-6">
            <h2 className="text-xl font-semibold border-b pb-1">{year}</h2>
            {monthKeys.map((month) => {
              const items = months.get(month)!;
              return (
                <div key={month} className="space-y-2">
                  <h3 className="text-sm font-medium opacity-70 capitalize">
                    {month} <span className="opacity-50">({items.length})</span>
                  </h3>
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
                    {items.flatMap((p) =>
                      p.assets
                        .filter((a) => IMAGE_EXT.includes(a.split(".").pop()?.toLowerCase() ?? ""))
                        .map((a) => (
                          <ImageLightbox
                            key={`${p.folder}/${p.slug}/${a}`}
                            src={kbAssetUrl(p.folder, a)}
                            alt={p.title}
                            className="w-full aspect-square object-cover rounded border"
                          />
                        ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
