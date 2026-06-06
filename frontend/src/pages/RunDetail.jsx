import { useParams } from "react-router-dom"
import { useEffect, useState } from "react"

import { Box, Typography, Chip } from "@mui/material"
import { DataGrid } from "@mui/x-data-grid"

export default function RunDetail() {
  const { runId } = useParams()
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}`)
      .then(r => r.json())
      .then(setData)
  }, [runId])

  if (!data) return <div>Loading...</div>

  const entities = data.entities || []

  const rows = entities.map((e, idx) => ({
    // IMPORTANT: stable fallback ID
    id: e.entity_id || `${e.canonical_name}-${idx}`,

    name: e.canonical_name,
    type: e.entity_type,
    aliases: (e.aliases || []).join(", "),
  }))

  const columns = [
    {
      field: "name",
      headerName: "Entity",
      flex: 2
    },
    {
      field: "type",
      headerName: "Type",
      flex: 1,
      renderCell: (params) => {
        const value = params.value

        return (
          <Chip
            label={value}
            color={
              value === "company"
                ? "primary"
                : value === "person"
                ? "success"
                : value === "agreement"
                ? "warning"
                : "default"
            }
            size="small"
          />
        )
      }
    },
    {
      field: "aliases",
      headerName: "Aliases",
      flex: 3
    }
  ]

  return (
    <Box sx={{ height: "80vh", width: "100%", p: 2 }}>

      <Typography variant="h4" gutterBottom>
        Entities — {runId}
      </Typography>

      <DataGrid
        rows={rows}
        columns={columns}
        pageSizeOptions={[50, 100, 150]}
        initialState={{
          pagination: {
            paginationModel: { pageSize: 50, page: 0 }
          }
        }}
      />

    </Box>
  )
}