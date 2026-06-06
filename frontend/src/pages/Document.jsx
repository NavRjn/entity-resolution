import { useParams } from "react-router-dom"
import { useEffect, useState, useMemo } from "react"

import { Box, Typography, Chip } from "@mui/material"

export default function Document() {
  const { runId } = useParams()
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}/document`)
      .then(r => r.json())
      .then(setData)
  }, [runId])

  // 👇 ALWAYS define derived state BEFORE return
  const text = data?.document || ""
  const entities = data?.entities || []

  const entityNames = useMemo(() => {
    return entities.map(e => e.canonical_name)
  }, [entities])

  if (!data) return <div>Loading...</div>

  function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }

  function highlightText(text, entities) {
    if (!entities.length) return text

    let result = text

    entities.forEach((e) => {
      const name = e.canonical_name
      if (!name) return

      const regex = new RegExp(`\\b${escapeRegExp(name)}\\b`, "g")

      result = result.replace(
        regex,
        `<mark style="background:#fff3cd;padding:2px;border-radius:4px;">${name}</mark>`
      )
    })

    return result
  }

  const highlighted = highlightText(text, entities)

  return (
    <Box sx={{ padding: 3 }}>

      <Typography variant="h4" gutterBottom>
        Document — {runId}
      </Typography>

      <Box sx={{ marginBottom: 2 }}>
        {entities.slice(0, 10).map((e, idx) => (
          <Chip
            key={idx}
            label={`${e.canonical_name} (${e.entity_type})`}
            size="small"
            sx={{ marginRight: 1, marginBottom: 1 }}
          />
        ))}
      </Box>

      <Box
        sx={{
          whiteSpace: "pre-wrap",
          lineHeight: 1.6,
          fontSize: 14,
          backgroundColor: "#fafafa",
          padding: 2,
          borderRadius: 2,
          border: "1px solid #eee"
        }}
        dangerouslySetInnerHTML={{ __html: highlighted }}
      />

    </Box>
  )
}