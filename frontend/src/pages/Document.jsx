import { useParams, useSearchParams } from "react-router-dom"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import rehypeRaw from "rehype-raw"
import rehypeSanitize from "rehype-sanitize"
import { ChevronLeft, ChevronRight } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import RunNav from "@/components/RunNav"
import { anchoredCitations, citationLabel, typeStyle } from "@/lib/entities"

const API = "http://localhost:8000"

/* ----------------------------- legacy (name-matching) rendering -----------------------------
   Used only for runs without anchored citations (old legacy runs), where offsets do not exist. */

function detectFormat(content = "") {
  if (/<(html|body|div|p|span|table|h1|h2|h3|section|article)[\s>]/i.test(content)) return "html"
  if (/^#|```|\*\*|^-|^\d+\.|\[.*\]\(.*\)/m.test(content)) return "markdown"
  return "text"
}

function escapeRegExp(str = "") {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function highlightByName(text, entities, onEntityClick) {
  const names = entities.map((e) => e?.canonical_name).filter(Boolean).sort((a, b) => b.length - a.length)
  if (!text || !names.length) return text
  const pattern = new RegExp(names.map(escapeRegExp).join("|"), "gi")
  const nodes = []
  let last = 0
  let m
  let i = 0
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    const name = names.find((n) => n.toLowerCase() === m[0].toLowerCase()) || m[0]
    nodes.push(
      <mark
        key={`${name}-${i++}`}
        data-entity={name.toLowerCase()}
        className="cursor-pointer rounded bg-yellow-200 px-1 hover:bg-yellow-300"
        onClick={() => onEntityClick(name)}
      >
        {m[0]}
      </mark>
    )
    last = pattern.lastIndex
  }
  nodes.push(text.slice(last))
  return nodes
}

function LegacyDocument({ text, entities, targetName }) {
  const format = useMemo(() => detectFormat(text), [text])
  const scrollTo = useCallback((name) => {
    const el = document.querySelector(`[data-entity="${String(name).toLowerCase()}"]`)
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [])
  useEffect(() => {
    if (targetName) setTimeout(() => scrollTo(targetName), 300)
  }, [targetName, scrollTo])

  const body =
    format === "markdown" ? (
      <ReactMarkdown
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{ p: ({ children }) => <p>{highlightByName(String(children), entities, scrollTo)}</p> }}
      >
        {text}
      </ReactMarkdown>
    ) : (
      <div className="whitespace-pre-wrap">{highlightByName(text, entities, scrollTo)}</div>
    )
  return <div className="prose prose-slate max-w-none text-left text-sm leading-6">{body}</div>
}

/* ----------------------------- citation-based rendering ----------------------------- */

/** Non-overlapping, validated highlight ranges: [{start, end, entity, cite}] sorted by position. */
function buildSpans(text, entities, range) {
  const all = []
  for (const entity of entities) {
    for (const c of anchoredCitations(entity)) {
      if (c.end_char <= text.length && text.slice(c.start_char, c.end_char) === c.quote) {
        all.push({ start: c.start_char, end: c.end_char, entity, cite: c.index })
      }
    }
  }
  all.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start))
  const spans = []
  let edge = -1
  for (const s of all) {
    if (s.start >= edge) {
      spans.push(s)
      edge = s.end
    }
  }
  if (!range) return spans
  const [rs, re] = range
  return [...spans.filter((s) => s.end <= rs || s.start >= re), { start: rs, end: re, range: true }].sort(
    (a, b) => a.start - b.start
  )
}

function CitedText({ text, spans, selected, onSelect }) {
  const nodes = []
  let pos = 0
  spans.forEach((s, i) => {
    if (s.start > pos) nodes.push(text.slice(pos, s.start))
    if (s.range) {
      nodes.push(
        <mark key={`r${i}`} id="span-target" className="rounded bg-yellow-200 px-0.5 ring-2 ring-yellow-500">
          {text.slice(s.start, s.end)}
        </mark>
      )
    } else {
      const isSel = selected?.entityId === s.entity.entity_id
      nodes.push(
        <mark
          key={`${s.entity.entity_id}-${s.cite}`}
          id={`cite-${s.entity.entity_id}-${s.cite}`}
          data-entity-id={s.entity.entity_id}
          title={`${s.entity.canonical_name} (${s.entity.entity_type})`}
          onClick={() => onSelect(s.entity.entity_id, s.cite)}
          className={`cursor-pointer rounded px-0.5 transition ${typeStyle(s.entity.entity_type).mark} ${
            isSel ? "ring-2 ring-foreground" : ""
          } ${isSel && selected.cite === s.cite ? "ring-offset-1" : ""}`}
        >
          {text.slice(s.start, s.end)}
        </mark>
      )
    }
    pos = s.end
  })
  nodes.push(text.slice(pos))
  return <div className="whitespace-pre-wrap break-words text-left text-sm leading-6">{nodes}</div>
}

function snippet(text, c) {
  const a = Math.max(0, c.start_char - 45)
  const b = Math.min(text.length, c.end_char + 45)
  return (
    <>
      {a > 0 && "…"}
      {text.slice(a, c.start_char)}
      <strong>{text.slice(c.start_char, c.end_char)}</strong>
      {text.slice(c.end_char, b)}
      {b < text.length && "…"}
    </>
  )
}

/* ----------------------------- page ----------------------------- */

export default function Document() {
  const { runId } = useParams()
  const [params, setParams] = useSearchParams()
  const entityParam = params.get("entity")
  const citeParam = Number(params.get("cite") ?? 0)
  const spanParam = params.get("span")

  const [text, setText] = useState("")
  const [entities, setEntities] = useState([])
  const [state, setState] = useState({ loading: true, error: null })
  const [filter, setFilter] = useState("")
  const bodyRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [runResp, docResp] = await Promise.all([
          fetch(`${API}/api/runs/${runId}`),
          fetch(`${API}/api/runs/${runId}/document`),
        ])
        const run = await runResp.json()
        if (!docResp.ok) {
          const detail = await docResp.json().catch(() => ({}))
          throw new Error(detail.detail || `Document unavailable (${docResp.status})`)
        }
        const doc = await docResp.json()
        if (cancelled) return
        setEntities(run.entities || [])
        setText(doc.document || "")
        setState({ loading: false, error: null })
      } catch (e) {
        if (!cancelled) setState({ loading: false, error: e.message })
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [runId])

  const range = useMemo(() => {
    const m = /^(\d+)-(\d+)$/.exec(spanParam || "")
    return m ? [Number(m[1]), Number(m[2])] : null
  }, [spanParam])

  const spans = useMemo(() => buildSpans(text, entities, range), [text, entities, range])
  const hasCitations = spans.some((s) => !s.range)

  // ?entity= may be an entity_id (new links) or a name (old links / legacy runs)
  const selectedEntity = useMemo(() => {
    if (!entityParam) return null
    const q = entityParam.toLowerCase()
    return (
      entities.find((e) => e.entity_id === entityParam) ||
      entities.find((e) => e.canonical_name?.toLowerCase() === q) ||
      null
    )
  }, [entities, entityParam])
  const selectedCites = useMemo(
    () =>
      selectedEntity
        ? anchoredCitations(selectedEntity).filter((c) =>
            spans.some((s) => s.entity?.entity_id === selectedEntity.entity_id && s.cite === c.index)
          )
        : [],
    [selectedEntity, spans]
  )
  const selected = selectedEntity ? { entityId: selectedEntity.entity_id, cite: citeParam } : null

  const select = useCallback(
    (entityId, cite = 0) => setParams({ entity: entityId, cite: String(cite) }, { replace: true }),
    [setParams]
  )

  // scroll to the requested citation / range once the highlights exist
  useEffect(() => {
    if (state.loading || !hasCitations) return
    const target = range
      ? document.getElementById("span-target")
      : selectedEntity &&
        (document.getElementById(`cite-${selectedEntity.entity_id}-${citeParam}`) ||
          document.querySelector(`[data-entity-id="${selectedEntity.entity_id}"]`))
    if (target) setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "center" }), 150)
  }, [state.loading, hasCitations, selectedEntity, citeParam, range])

  const step = (delta) => {
    if (!selectedCites.length) return
    const at = Math.max(0, selectedCites.findIndex((c) => c.index === citeParam))
    select(selectedEntity.entity_id, selectedCites[(at + delta + selectedCites.length) % selectedCites.length].index)
  }

  const visible = entities.filter((e) => e.canonical_name?.toLowerCase().includes(filter.toLowerCase()))

  if (state.loading) {
    return <div className="flex min-h-[50vh] items-center justify-center text-sm text-muted-foreground">Loading document...</div>
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-8 sm:py-10">
        <div className="mb-6">
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Document Review</div>
          <h1 className="mt-2 break-all text-2xl font-semibold sm:text-3xl">Run {runId}</h1>
          <p className="text-sm text-muted-foreground">
            {state.error ? "" : hasCitations
              ? `${spans.filter((s) => !s.range).length} highlighted citations, click one to select its entity`
              : "No anchored citations for this run: highlighting entities by name"}
          </p>
        </div>

        <RunNav runId={runId} className="mb-6" />

        {state.error ? (
          <Card>
            <CardContent className="pt-6 text-sm text-red-700">{state.error}</CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:h-fit">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Entities ({entities.length})</CardTitle>
                  <input
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter..."
                    className="mt-2 w-full rounded border px-2 py-1 text-sm"
                  />
                </CardHeader>
                <CardContent>
                  <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
                    {visible.map((e) => (
                      <li key={e.entity_id}>
                        <button
                          onClick={() => select(e.entity_id, anchoredCitations(e)[0]?.index ?? 0)}
                          className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-sm hover:bg-muted ${
                            selectedEntity?.entity_id === e.entity_id ? "bg-muted font-medium" : ""
                          }`}
                        >
                          <span className="truncate">{e.canonical_name}</span>
                          <Badge variant="outline" className={`shrink-0 ${typeStyle(e.entity_type).badge}`}>
                            {e.entity_type}
                          </Badge>
                        </button>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>

              {selectedEntity && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">{selectedEntity.canonical_name}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-sm">
                    {selectedEntity.aliases?.length > 0 && (
                      <div className="text-muted-foreground">Also: {selectedEntity.aliases.join(", ")}</div>
                    )}
                    {selectedCites.length > 0 ? (
                      <>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">
                            Citation {Math.max(1, selectedCites.findIndex((c) => c.index === citeParam) + 1)} of {selectedCites.length}
                          </span>
                          <span className="flex gap-1">
                            <Button size="icon" variant="outline" onClick={() => step(-1)} aria-label="Previous citation">
                              <ChevronLeft className="size-4" />
                            </Button>
                            <Button size="icon" variant="outline" onClick={() => step(1)} aria-label="Next citation">
                              <ChevronRight className="size-4" />
                            </Button>
                          </span>
                        </div>
                        <ul className="space-y-2">
                          {selectedCites.map((c) => (
                            <li key={c.index}>
                              <button
                                onClick={() => select(selectedEntity.entity_id, c.index)}
                                className={`w-full rounded border p-2 text-left text-xs leading-5 hover:bg-muted ${
                                  c.index === citeParam ? "border-foreground" : ""
                                }`}
                              >
                                <span className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                                  {citationLabel(c)}
                                </span>
                                {snippet(text, c)}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : (
                      <div className="text-muted-foreground">No located citation for this entity.</div>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>

            <Card className="min-w-0">
              <CardHeader>
                <CardTitle className="text-sm">Document</CardTitle>
              </CardHeader>
              <CardContent>
                <div ref={bodyRef}>
                  {hasCitations ? (
                    <CitedText text={text} spans={spans} selected={selected} onSelect={select} />
                  ) : (
                    <LegacyDocument text={text} entities={entities} targetName={entityParam} />
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
