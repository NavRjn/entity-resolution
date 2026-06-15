import { useParams, useSearchParams } from "react-router-dom"
import { useEffect, useMemo, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
// import remarkGfm from "remark-gfm"
import rehypeRaw from "rehype-raw"
import rehypeSanitize from "rehype-sanitize"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/* ----------------------------- utilities ----------------------------- */

function detectFormat(content = "") {
  if (/<(html|body|div|p|span|table|h1|h2|h3|section|article)[\s>]/i.test(content)) {
    return "html"
  }

  if (/^#|```|\*\*|^\-|^\d+\.|\[.*\]\(.*\)/m.test(content)) {
    return "markdown"
  }

  return "text"
}

function escapeRegExp(str = "") {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/* ----------------------------- entity mark ----------------------------- */

function EntityMark({ name, children, onClick }) {
  return (
    <mark
      data-entity={name}
      className="bg-yellow-200 px-1 rounded cursor-pointer hover:bg-yellow-300 transition"
      onClick={onClick}
    >
      {children}
    </mark>
  )
}

/* ----------------------------- text highlighter ----------------------------- */

function highlightTextToReact(text, entities, onEntityClick) {
  if (!text || !entities?.length) return text

  const sorted = [...entities]
    .filter(e => e?.canonical_name)
    .sort((a, b) => b.canonical_name.length - a.canonical_name.length)

  const pattern = new RegExp(
    sorted.map(e => escapeRegExp(e.canonical_name)).join("|"),
    "gi"
  )

  const nodes = []
  let lastIndex = 0
  let match
  let i = 0

  while ((match = pattern.exec(text)) !== null) {
    const start = match.index
    const end = pattern.lastIndex
    const matched = text.slice(start, end)

    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start))
    }

    const entity = sorted.find(
      e => e.canonical_name.toLowerCase() === matched.toLowerCase()
    )

    const name = entity?.canonical_name || matched
    const id = `${name}-${i++}`.toLowerCase().replace(/\s+/g, "-")

    nodes.push(
      <EntityMark
        key={id}
        name={name.toLowerCase()}
        onClick={() => onEntityClick(name)}
      >
        {matched}
      </EntityMark>
    )

    lastIndex = end
  }

  nodes.push(text.slice(lastIndex))
  return nodes
}

/* ----------------------------- HTML renderer ----------------------------- */

function HtmlRenderer({ html, entities, onEntityClick }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current) return

    const walker = document.createTreeWalker(ref.current, NodeFilter.SHOW_TEXT)

    const nodes = []
    let node

    while ((node = walker.nextNode())) {
      nodes.push(node)
    }

    for (const textNode of nodes) {
      let text = textNode.nodeValue

      for (const e of entities) {
        const name = e.canonical_name
        if (!name) continue

        const regex = new RegExp(escapeRegExp(name), "gi")

        text = text.replace(regex, (m) => {
          const safe = name.toLowerCase()
          return `<mark data-entity="${safe}" class="bg-yellow-200 px-1 rounded cursor-pointer">${m}</mark>`
        })
      }

      const span = document.createElement("span")
      span.innerHTML = text
      textNode.replaceWith(span)
    }

    // attach click handlers
    ref.current.querySelectorAll("[data-entity]").forEach(el => {
      el.addEventListener("click", () => {
        onEntityClick(el.getAttribute("data-entity"))
      })
    })
  }, [html, entities])

  return (
    <div ref={ref} dangerouslySetInnerHTML={{ __html: html }} />
  )
}

/* ----------------------------- markdown renderer ----------------------------- */

function MarkdownRenderer({ content, entities, onEntityClick }) {
  return (
    <ReactMarkdown
      // remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, rehypeSanitize]}
      components={{
        p({ children }) {
          const text = String(children)

          return (
            <p>
              {highlightTextToReact(text, entities, onEntityClick)}
            </p>
          )
        }
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

/* ----------------------------- main component ----------------------------- */

export default function Document() {
  const { runId } = useParams()
  const [searchParams] = useSearchParams()
  const targetEntity = searchParams.get("entity")

  const [documentText, setDocumentText] = useState("")
  const [entities, setEntities] = useState([])
  const [loading, setLoading] = useState(true)

  const containerRef = useRef(null)

  useEffect(() => {
    async function load() {
      const [runResp, docResp] = await Promise.all([
        fetch(`http://localhost:8000/api/runs/${runId}`),
        fetch(`http://localhost:8000/api/runs/${runId}/document`)
      ])

      const runData = await runResp.json()
      const docData = await docResp.json()

      setEntities(runData.entities || [])
      setDocumentText(docData.document || "")
      setLoading(false)
    }

    load()
  }, [runId])

  const format = useMemo(() => detectFormat(documentText), [documentText])

  const scrollToEntity = (name) => {
    const el = document.querySelector(`[data-entity="${name.toLowerCase()}"]`)
    if (!el) return

    el.scrollIntoView({ behavior: "smooth", block: "center" })
    el.classList.add("ring-2", "ring-yellow-400")

    setTimeout(() => {
      el.classList.remove("ring-2", "ring-yellow-400")
    }, 2000)
  }

  useEffect(() => {
    if (!targetEntity) return
    setTimeout(() => scrollToEntity(targetEntity), 300)
  }, [targetEntity])

  const rendered = useMemo(() => {
    const onEntityClick = (name) => {
      scrollToEntity(name)
      window.history.replaceState(null, "", `?entity=${encodeURIComponent(name)}`)
    }

    if (format === "html") {
      return (
        <HtmlRenderer
          html={documentText}
          entities={entities}
          onEntityClick={onEntityClick}
        />
      )
    }

    if (format === "markdown") {
      return (
        <MarkdownRenderer
          content={documentText}
          entities={entities}
          onEntityClick={onEntityClick}
        />
      )
    }

    return (
      <div>
        {highlightTextToReact(documentText, entities, scrollToEntity)}
      </div>
    )
  }, [documentText, entities, format])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading document...
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-7xl px-8 py-10">

        {/* Header */}
        <div className="mb-8">
          <div className="text-xs uppercase tracking-widest text-muted-foreground">
            Document Review
          </div>

          <h1 className="mt-2 text-3xl font-semibold">
            Run {runId}
          </h1>

          <p className="text-sm text-muted-foreground">
            Format: {format.toUpperCase()}
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[260px_1fr]">

          {/* Sidebar */}
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="text-sm">Entities</CardTitle>
            </CardHeader>

            <CardContent>
              <div className="flex flex-wrap gap-2">
                {entities.slice(0, 50).map((e) => (
                  <Badge
                    key={e.entity_id}
                    variant="secondary"
                    className="cursor-pointer"
                    onClick={() => scrollToEntity(e.canonical_name)}
                  >
                    {e.canonical_name}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Document */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Document</CardTitle>
            </CardHeader>

            <CardContent>
              <div
                ref={containerRef}
                className="prose prose-slate max-w-none text-sm leading-6"
              >
                {rendered}
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  )
}