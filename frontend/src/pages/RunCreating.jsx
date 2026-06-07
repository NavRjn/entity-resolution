import { useEffect, useState } from "react"
import { useNavigate, useLocation } from "react-router-dom"
import { CircularProgress, Box, Typography } from "@mui/material"

export default function RunCreating() {
  const navigate = useNavigate()
  const location = useLocation()
  const { uploadId } = location.state || {}
  const [runId, setRunId] = useState(null)

  useEffect(() => {
    if (!uploadId) {
      navigate("/uploads")
      return
    }

    async function startRun() {
      const resp = await fetch(`http://localhost:8000/api/uploads/${uploadId}/run`, {
        method: "POST"
      })
      const data = await resp.json()
      setRunId(data.run_id)
    }

    startRun()
  }, [uploadId, navigate])

  useEffect(() => {
    if (!runId) return

    const interval = setInterval(async () => {
      const resp = await fetch(`http://localhost:8000/api/runs/${runId}`)
      const data = await resp.json()
      if (data.status === "completed") {
        clearInterval(interval)
        navigate(`/runs/${runId}`)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [runId, navigate])

  return (
    <Box sx={{ height: "80vh", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 2 }}>
      <CircularProgress />
      <Typography variant="h6">Creating run...</Typography>
    </Box>
  )
}