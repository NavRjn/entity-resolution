import { useParams, useSearchParams } from "react-router-dom"
import { useEffect, useState } from "react"
import { Box, Typography, Chip } from "@mui/material"

export default function Document() {
  const { runId } = useParams()
  const [searchParams] = useSearchParams()

  const targetEntity = searchParams.get("entity")

  const [documentText, setDocumentText] = useState("")
  const [entities, setEntities] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadData() {
      try {
        const [runResp, docResp] = await Promise.all([
          fetch(`http://localhost:8000/api/runs/${runId}`),
          fetch(`http://localhost:8000/api/runs/${runId}/document`)
        ])

        const runData = await runResp.json()
        const docData = await docResp.json()

        setEntities(runData.entities || [])
        setDocumentText(docData.document || "")
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [runId])

  function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  }

  function normalize(str) {
    return (str || "")
      .toLowerCase()
      .trim()
      .replace(/\s+/g, " ")
  }

  function highlightText(text) {
    let result = text

    for (const entity of entities) {
      const name = entity.canonical_name
      if (!name) continue

      const regex = new RegExp(escapeRegExp(name), "gi")

      result = result.replace(
        regex,
        (match) =>
          `<mark id="ent-${normalize(match)}"
            style="
              background:#fff3cd;
              padding:2px;
              border-radius:4px;
            "
          >${match}</mark>`
      )
    }

    return result
  }

  useEffect(() => {
    if (!targetEntity) return
    if (entities.length === 0) return

    const normalized = normalize(targetEntity)

    const timer = setTimeout(() => {
      const el = document.getElementById(`ent-${normalized}`)

      if (el) {
        el.scrollIntoView({
          behavior: "smooth",
          block: "center"
        })

        el.style.background = "#ffe082"
      } else {
        console.warn("Could not find:", normalized)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [targetEntity, entities])

  if (loading) return <div>Loading...</div>

  return (
    <Box sx={{ p: 3 }}>

      <Typography variant="h4" gutterBottom>
        Document — {runId}
      </Typography>

      <Box sx={{ mb: 2 }}>
        {entities.slice(0, 20).map((e) => (
          <Chip
            key={e.entity_id}
            label={e.canonical_name}
            size="small"
            sx={{ mr: 1, mb: 1 }}
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
        dangerouslySetInnerHTML={{
          __html: highlightText(documentText)
        }}
      />

    </Box>
  )
}