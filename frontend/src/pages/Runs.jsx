import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

import { Input } from "@/components/ui/input"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { Badge } from "@/components/ui/badge"

import { Search, ArrowRight } from "lucide-react"

export default function Runs() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")

  useEffect(() => {
    fetch("http://localhost:8000/api/runs")
      .then((r) => r.json())
      .then((data) => {
        setRuns(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const filteredRuns = useMemo(() => {
    return runs.filter((run) =>
      run.run_id?.toLowerCase().includes(search.toLowerCase())
    )
  }, [runs, search])

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-6xl px-6 py-10 space-y-8">

        {/* HEADER */}
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">
            Runs
          </h1>
          <p className="text-muted-foreground">
            Monitor and inspect analysis execution history.
          </p>
        </div>

        {/* KPI STRIP */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="shadow-sm">
            <CardContent className="p-5">
              <p className="text-sm text-muted-foreground">
                Total Runs
              </p>
              <p className="text-2xl font-semibold mt-1">
                {runs.length}
              </p>
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardContent className="p-5">
              <p className="text-sm text-muted-foreground">
                Active Filters
              </p>
              <p className="text-2xl font-semibold mt-1">
                {search ? 1 : 0}
              </p>
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardContent className="p-5">
              <p className="text-sm text-muted-foreground">
                Status
              </p>
              <p className="text-2xl font-semibold mt-1">
                System OK
              </p>
            </CardContent>
          </Card>
        </div>

        {/* TOOLBAR */}
        <div className="flex items-center justify-between gap-4">
          <div className="relative w-full max-w-md">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground"/>
            <Input
                placeholder="Search runs by ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
            />
          </div>
        </div>

        {/* TABLE */}
        <Card className="shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-medium">
              Run History
            </CardTitle>
          </CardHeader>

          <CardContent className="p-0">
            {loading ? (
                <div className="p-10 text-sm text-muted-foreground">
                  Loading runs...
                </div>
            ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40">
                      <TableHead>Run ID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">
                        Action
                      </TableHead>
                    </TableRow>
                  </TableHeader>

                  <TableBody>
                    {filteredRuns.length === 0 ? (
                        <TableRow>
                          <TableCell
                              colSpan={3}
                              className="h-24 text-center text-muted-foreground"
                          >
                            No runs found
                          </TableCell>
                        </TableRow>
                    ) : (
                        filteredRuns.map((run) => (
                            <TableRow
                                key={run.run_id}
                                className="hover:bg-muted/50 transition-colors"
                            >
                              <TableCell className="font-mono text-sm">
                                {run.run_id}
                              </TableCell>

                              <TableCell>
                                <Badge variant="secondary">
                                  {run.status || "unknown"}
                                </Badge>
                              </TableCell>

                              <TableCell className="text-right">
                                <Link
                                    to={`/runs/${run.run_id}`}
                                    className="inline-flex items-center gap-2 text-sm font-medium hover:underline"
                                >
                                  Open
                                  <ArrowRight className="h-4 w-4"/>
                                </Link>
                              </TableCell>
                            </TableRow>
                        ))
                    )}
                  </TableBody>
                </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}