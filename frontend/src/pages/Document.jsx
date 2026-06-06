import { useParams, useSearchParams } from "react-router-dom"
import { useEffect, useState } from "react"

import { Box, Typography, Chip } from "@mui/material"

export default function Document() {
  const { runId } = useParams()
  const [searchParams] = useSearchParams()

  const targetEntity = searchParams.get("entity")

  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}/document`)
      .then(r => r.json())
      .then(setData)
  }, [runId])

  const text = data?.document || ""
  const entities = data?.entities || []

  function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }

  function highlightText(text, entities) {
    if (!entities.length) return text

    let result = text

    for (const e of entities) {
      const name = e.canonical_name
      if (!name) continue

      const regex = new RegExp(`\\b${escapeRegExp(name)}\\b`, "g")

      result = result.replace(
        regex,
        `<mark id="ent-${name}" style="
          background:#fff3cd;
          padding:2px;
          border-radius:4px;
        ">${name}</mark>`
      )
    }

    return result
  }

  const highlighted = highlightText(text, entities)

  useEffect(() => {
    if (!targetEntity) return

    const el = document.getElementById(`ent-${targetEntity}`)

    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
      el.style.background = "#ffe082"
    }
  }, [targetEntity, entities])

  if (!data) return <div>Loading...</div>

  return (
    <Box sx={{ padding: 3 }}>

      <Typography variant="h4" gutterBottom>
        Document — {runId}
      </Typography>

      {/* Entity chips */}
      <Box sx={{ marginBottom: 2 }}>
        {entities.slice(0, 10).map((e, idx) => (
          <Chip
            key={idx}
            label={e.canonical_name}
            size="small"
            sx={{ marginRight: 1, marginBottom: 1 }}
          />
        ))}
      </Box>

      {/* Document */}
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