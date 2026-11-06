import { Link, useLocation } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

const TABS = [
  { key: "entities", label: "Entities", to: (id) => `/runs/${id}` },
  { key: "relationships", label: "Relationships", to: (id) => `/runs/${id}/relationships` },
  { key: "document", label: "Document", to: (id) => `/runs/${id}/document` },
  { key: "graph", label: "Graph", to: (id) => `/runs/${id}/graph` },
]

function activeKey(pathname) {
  if (pathname.endsWith("/relationships")) return "relationships"
  if (pathname.endsWith("/document")) return "document"
  if (pathname.endsWith("/graph")) return "graph"
  return "entities"
}

/** The one navigation bar shared by the four run views, so every view links to every other. */
export default function RunNav({ runId, className = "" }) {
  const { pathname } = useLocation()
  const active = activeKey(pathname)

  return (
    <div className={`flex flex-wrap items-center gap-6 border-b ${className}`}>
      <Link
        to="/runs"
        className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3" /> All runs
      </Link>

      <nav className="flex gap-8" aria-label="Run views">
        {TABS.map((tab) => (
          <Link
            key={tab.key}
            to={tab.to(runId)}
            aria-current={active === tab.key ? "page" : undefined}
            className={`pb-3 text-sm font-medium transition-colors ${
              active === tab.key
                ? "border-b-2 border-foreground text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}
