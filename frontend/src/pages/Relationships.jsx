import { useParams } from "react-router-dom"
import { useEffect, useState, useMemo } from "react"

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

export default function Relationships() {
  const { runId } = useParams()
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}`)
      .then((r) => r.json())
      .then(setData)
  }, [runId])

  const entities = data?.entities || []
  const relationships = data?.relationships || []

  const entityMap = useMemo(() => {
    const map = {}

    for (const e of entities) {
      map[e.entity_id] = e.canonical_name
    }

    return map
  }, [entities])

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-muted-foreground">
          Loading relationships...
        </div>
      </div>
    )
  }

  const rows = relationships.map((r, idx) => ({
    id: `${r.source_entity_id}-${r.target_entity_id}-${idx}`,
    source:
      entityMap[r.source_entity_id] || r.source_entity_id,
    target:
      entityMap[r.target_entity_id] || r.target_entity_id,
    type: r.relationship_type,
    evidence: r.citation?.quote || "No evidence available",
  }))

  const uniqueTypes = new Set(
    relationships.map((r) => r.relationship_type)
  ).size

  const connectedEntities = new Set([
    ...relationships.map((r) => r.source_entity_id),
    ...relationships.map((r) => r.target_entity_id),
  ]).size

  const relationshipColor = (type) => {
    const value = (type || "").toLowerCase()

    if (
      value.includes("own") ||
      value.includes("subsidiary")
    ) {
      return "bg-blue-50 text-blue-700 border-blue-200"
    }

    if (
      value.includes("sign") ||
      value.includes("execute")
    ) {
      return "bg-emerald-50 text-emerald-700 border-emerald-200"
    }

    if (
      value.includes("party") ||
      value.includes("agreement")
    ) {
      return "bg-amber-50 text-amber-700 border-amber-200"
    }

    return ""
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
            Relationship Analysis
          </h1>

          <p className="mt-2 text-muted-foreground">
            Run ID: {runId}
          </p>
        </div>

        {/* Metrics */}

        <div className="mb-8 grid gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {relationships.length}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Relationships
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {uniqueTypes}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Relationship Types
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <div className="text-3xl font-semibold">
                {connectedEntities}
              </div>

              <div className="mt-1 text-sm text-muted-foreground">
                Connected Entities
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Table */}

        <Card>
          <CardHeader>
            <CardTitle>
              Extracted Relationships
            </CardTitle>
          </CardHeader>

          <CardContent>
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[20%]">
                      Source
                    </TableHead>

                    <TableHead className="w-[15%]">
                      Relationship
                    </TableHead>

                    <TableHead className="w-[20%]">
                      Target
                    </TableHead>

                    <TableHead>
                      Evidence
                    </TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">
                        {row.source}
                      </TableCell>

                      <TableCell>
                        <Badge
                          variant="outline"
                          className={relationshipColor(
                            row.type
                          )}
                        >
                          {row.type}
                        </Badge>
                      </TableCell>

                      <TableCell className="font-medium">
                        {row.target}
                      </TableCell>

                      <TableCell className="max-w-xl text-muted-foreground">
                        <div className="line-clamp-2">
                          {row.evidence}
                        </div>
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
