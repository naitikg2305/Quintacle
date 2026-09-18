// Tiny class-name joiner — enough for the UI kit, no dependency needed.
export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
