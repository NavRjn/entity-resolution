import { useParams, useNavigate } from "react-router-dom"
import { useEffect, useState } from "react"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

import { Badge } from "@/components/ui/badge"
import RunNav from "@/components/RunNav"
import { anchoredCitations, citationLabel, citationLink, typeStyle } from "@/lib/entities"

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

  const count = (t) => entities.filter((e) => (e.entity_type || "").toLowerCase() === t).length
  const companies = count("company")
  const people = count("person")
  const agreements = count("agreement")
  const others = entities.length - companies - people - agreements

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

        <div className="mb-8 grid gap-4 md:grid-cols-5">
          {[
            ["Total entities", entities.length],
            ["Companies", companies],
            ["People", people],
            ["Agreements", agreements],
            ["Other / assets", others],
          ].map(([label, n]) => (
            <Card key={label}>
              <CardContent className="pt-6">
                <div className="text-3xl font-semibold">{n}</div>
                <div className="mt-1 text-sm text-muted-foreground">{label}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <RunNav runId={runId} className="mb-8" />

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

                    <TableHead className="w-[22%]">
                      Citations
                    </TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {entities.map((entity, idx) => {
                    const cites = anchoredCitations(entity)
                    return (
                      <TableRow
                        key={entity.entity_id || idx}
                        className="cursor-pointer transition-colors hover:bg-muted/50"
                        onClick={() => navigate(citationLink(runId, entity, cites[0]?.index ?? 0))}
                      >
                        <TableCell className="font-medium">{entity.canonical_name}</TableCell>

                        <TableCell>
                          <Badge variant="outline" className={typeStyle(entity.entity_type).badge}>
                            {entity.entity_type}
                          </Badge>
                        </TableCell>

                        <TableCell className="text-muted-foreground">
                          {(entity.aliases || []).join(", ")}
                        </TableCell>

                        <TableCell className="text-xs text-muted-foreground">
                          {cites.length > 0
                            ? `${cites.length} in document (${citationLabel(cites[0])})`
                            : "not located"}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}