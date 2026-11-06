import { useEffect, useState } from "react"
import { useNavigate, useLocation } from "react-router-dom"
import { CircularProgress, Box, Typography } from "@mui/material"

export default function RunCreating() {
  const navigate = useNavigate()
  const location = useLocation()
  const { uploadId } = location.state || {}
  const [runId, setRunId] = useState(null)
  const [error, setError] = useState(null)

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
      } else if (data.status === "failed") {
        clearInterval(interval)
        setError(data.error || "The run failed.")
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [runId, navigate])

  return (
    <Box sx={{ height: "80vh", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 2 }}>
      {error ? (
        <>
          <Typography variant="h6" color="error">Run failed</Typography>
          <Typography variant="body2" sx={{ maxWidth: 560, textAlign: "center" }}>{error}</Typography>
          <Typography variant="body2">Run ID: {runId}</Typography>
        </>
      ) : (
        <>
          <CircularProgress />
          <Typography variant="h6">Creating run...</Typography>
        </>
      )}
    </Box>
  )
}