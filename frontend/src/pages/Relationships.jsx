import { useParams } from "react-router-dom"
import { useEffect, useState, useMemo } from "react"

import { Box, Typography, Chip } from "@mui/material"
import { DataGrid } from "@mui/x-data-grid"

export default function Relationships() {
  const { runId } = useParams()
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}`)
      .then(r => r.json())
      .then(setData)
  }, [runId])

  // ALWAYS define derived data BEFORE return
  const entities = data?.entities || []
  const relationships = data?.relationships || []

  // safe lookup map
  const entityMap = useMemo(() => {
    const map = {}
    for (const e of entities) {
      map[e.entity_id] = e.canonical_name
    }
    return map
  }, [entities])

  if (!data) return <div>Loading...</div>

  const rows = relationships.map((r, idx) => ({
    id: `${r.source_entity_id}-${r.target_entity_id}-${idx}`,

    source: entityMap[r.source_entity_id] || r.source_entity_id,
    target: entityMap[r.target_entity_id] || r.target_entity_id,

    type: r.relationship_type,
    evidence: r.citation?.quote || "-"
  }))

  const columns = [
    { field: "source", headerName: "Source", flex: 1.5 },
    {
      field: "type",
      headerName: "Type",
      flex: 1,
      renderCell: (params) => (
        <Chip label={params.value} color="warning" size="small" />
      )
    },
      { field: "target", headerName: "Target", flex: 1.5 },
    { field: "evidence", headerName: "Evidence", flex: 3 }
  ]

  return (
    <Box sx={{ height: "80vh", width: "100%", p: 2 }}>
      <Typography variant="h4" gutterBottom>
        Relationships — {runId}
      </Typography>

      <DataGrid
        rows={rows}
        columns={columns}
        pageSizeOptions={[10, 25, 50]}
        initialState={{
          pagination: {
            paginationModel: { pageSize: 10, page: 0 }
          }
        }}
      />
    </Box>
  )
}