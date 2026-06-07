import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Box, Typography, Button, TextField } from "@mui/material"

export default function UploadNew() {
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleUpload() {
    if (!file) return
    setLoading(true)
    try {
      const formData = new FormData()
      formData.append("file", file)

      const resp = await fetch("http://localhost:8000/api/uploads", {
        method: "POST",
        body: formData
      })
      const data = await resp.json()

      // Auto-create a run after upload
      const runResp = await fetch("http://localhost:8000/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: data.upload_id })
      })
      const runData = await runResp.json()
      navigate(`/runs/${runData.run_id}`)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Upload New File
      </Typography>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0])}
        accept=".txt"
      />
      <Box sx={{ mt: 2 }}>
        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={!file || loading}
        >
          {loading ? "Uploading..." : "Upload & Create Run"}
        </Button>
      </Box>
    </Box>
  )
}