// Graph/index id → the page that shows it. Ids follow graph.py's scheme
// ("note:<folder>/<slug>", "journal:<iso>", "todo:<id>", "expense:<n>" …);
// notes deep-link into Browse the same way chat links do.
export function nodeHref(id: string): string | null {
  const [kind, rest] = [id.slice(0, id.indexOf(":")), id.slice(id.indexOf(":") + 1)];
  if (kind === "note") {
    const cut = rest.lastIndexOf("/");
    if (cut < 0) return null;
    return `/kb/browse?path=${encodeURIComponent(rest.slice(0, cut))}&open=${encodeURIComponent(rest.slice(cut + 1))}`;
  }
  const pages: Record<string, string> = {
    journal: "/journal",
    todo: "/todos",
    expense: "/finance",
    income: "/finance",
    activity: "/day",
    food: "/day",
    exercise: "/day",
    meal: "/habits",
    routine: "/habits",
    experience: "/travel",
    stock_tx: "/stocks",
    holding: "/stocks",
  };
  return pages[kind] ?? null;
}
