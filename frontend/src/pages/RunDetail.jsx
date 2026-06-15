import { useParams, Link, useNavigate, useLocation } from "react-router-dom"
import { useEffect, useState } from "react"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

import { Badge } from "@/components/ui/badge"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export default function RunDetail() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}`)
      .then((r) => r.json())
      .then(setData)
  }, [runId])

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-muted-foreground">
          Loading analysis...
        </div>
      </div>
    )
  }

  const entities = data.entities || []

  const companies = entities.filter(
    (e) => e.entity_type === "company"
  ).length

  const people = entities.filter(
    (e) => e.entity_type === "person"
  ).length

  const agreements = entities.filter(
    (e) => e.entity_type === "agreement"
  ).length

  const badgeClass = (type) => {
    switch (type) {
      case "company":
        return "bg-blue-50 text-blue-700 border-blue-200"

      case "person":
        return "bg-emerald-50 text-emerald-700 border-emerald-200"

      case "agreement":
        return "bg-amber-50 text-amber-700 border-amber-200"

      default:
        return ""
    }
  }

  const activeTab = () => {
    if (location.pathname.includes("relationships")) {
      return "relationships"
    }

    if (location.pathname.includes("document")) {
      return "document"
    }

    return "entities"
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-7xl px-8 py-10">
        {/* Header */}

        <div className="mb-10">
          <div className="text-xs font-medium uppercase tracking-widest text-muted-foreground">
            Legal Intelligence Platform
          </div>

          <h1 className="mt-3 text-4xl font-semibold tracking-tight">
            Entity Analysis
          </h1>

          <p className="mt-2 text-muted-foreground">
            Run ID: {runId}
          </p>
        </div>

        {/* KPI Cards */}

        <div className="mb-8 grid gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {entities.length}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Total Entities
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {companies}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Companies
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {people + agreements}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Other Entities
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Navigation */}

        <div className="mb-8 border-b">
          <nav className="flex gap-8">
            <Link
              to={`/runs/${runId}`}
              className={`pb-3 text-sm font-medium transition-colors ${
                activeTab() === "entities"
                  ? "border-b-2 border-foreground text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Entities
            </Link>

            <Link
              to={`/runs/${runId}/relationships`}
              className={`pb-3 text-sm font-medium transition-colors ${
                activeTab() === "relationships"
                  ? "border-b-2 border-foreground text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Relationships
            </Link>

            <Link
              to={`/runs/${runId}/document`}
              className={`pb-3 text-sm font-medium transition-colors ${
                activeTab() === "document"
                  ? "border-b-2 border-foreground text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Document
            </Link>
          </nav>
        </div>

        {/* Table */}

        <Card>
          <CardHeader>
            <CardTitle>Detected Entities</CardTitle>
          </CardHeader>

          <CardContent>
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[35%]">
                      Entity
                    </TableHead>

                    <TableHead>
                      Type
                    </TableHead>

                    <TableHead>
                      Aliases
                    </TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {entities.map((entity, idx) => (
                    <TableRow
                      key={entity.entity_id || idx}
                      className="cursor-pointer transition-colors hover:bg-muted/50"
                      onClick={() =>
                        navigate(
                          `/runs/${runId}/document?entity=${encodeURIComponent(
                            entity.canonical_name
                          )}`
                        )
                      }
                    >
                      <TableCell className="font-medium">
                        {entity.canonical_name}
                      </TableCell>

                      <TableCell>
                        <Badge
                          variant="outline"
                          className={badgeClass(
                            entity.entity_type
                          )}
                        >
                          {entity.entity_type}
                        </Badge>
                      </TableCell>

                      <TableCell className="text-muted-foreground">
                        {(entity.aliases || []).join(", ")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}