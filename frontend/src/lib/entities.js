/** Shared presentation helpers for entity types and citations. */

export const TYPE_STYLE = {
  company: { badge: "bg-blue-50 text-blue-700 border-blue-200", mark: "bg-blue-100 hover:bg-blue-200", node: "#0ea5e9" },
  person: { badge: "bg-emerald-50 text-emerald-700 border-emerald-200", mark: "bg-emerald-100 hover:bg-emerald-200", node: "#4f46e5" },
  agreement: { badge: "bg-amber-50 text-amber-700 border-amber-200", mark: "bg-amber-100 hover:bg-amber-200", node: "#f59e0b" },
  asset: { badge: "bg-violet-50 text-violet-700 border-violet-200", mark: "bg-violet-100 hover:bg-violet-200", node: "#8b5cf6" },
  other: { badge: "bg-slate-50 text-slate-700 border-slate-200", mark: "bg-slate-200 hover:bg-slate-300", node: "#64748b" },
}

export const typeStyle = (type) => TYPE_STYLE[(type || "").toLowerCase()] || TYPE_STYLE.other

/** Citations that point at a real range of the document text (docling placeholders and legacy zeros are excluded). */
export function anchoredCitations(entity) {
  return (entity.citations || [])
    .map((c, index) => ({ ...c, index }))
    .filter((c) => c.end_char > c.start_char)
}

export function citationLabel(c) {
  if (c.match === "verbatim") return "exact quote"
  if (c.match === "name_search") return "name match"
  if (c.match === "cooccurrence") return "co-mentioned"
  return c.match || ""
}

/** Link to the document view positioned at an entity's n-th citation. */
export function citationLink(runId, entity, index = 0) {
  return `/runs/${runId}/document?entity=${encodeURIComponent(entity.entity_id)}&cite=${index}`
}

/** Link to the document view highlighting an arbitrary character range (relationship evidence). */
export function spanLink(runId, c) {
  return `/runs/${runId}/document?span=${c.start_char}-${c.end_char}`
}
