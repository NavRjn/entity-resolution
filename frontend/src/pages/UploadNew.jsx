import { useState, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { Box, Typography, Button, Paper, Fade } from "@mui/material"

export default function UploadNew() {
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  const inputRef = useRef(null)
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

      await fetch("http://localhost:8000/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: data.upload_id })
      })

      navigate("/runs/creating", {
        state: { uploadId: data.upload_id }
      })
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  function onFileSelect(file) {
    if (!file) return
    setFile(file)
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragActive(false)

    const dropped = e.dataTransfer.files?.[0]
    if (dropped) onFileSelect(dropped)
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        px: 3,
        background: `
          radial-gradient(circle at 20% 20%, #e0f2fe 0%, transparent 40%),
          radial-gradient(circle at 80% 30%, #ede9fe 0%, transparent 45%),
          radial-gradient(circle at 50% 80%, #fef3c7 0%, transparent 40%),
          #f8fafc
        `
      }}
    >
      <Fade in timeout={600}>
        <Paper
          elevation={0}
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault()
            setDragActive(true)
          }}
          onDragLeave={() => setDragActive(false)}
          sx={{
            width: "100%",
            maxWidth: 560,
            p: 5,
            borderRadius: 5,
            position: "relative",
            overflow: "hidden",
            background: "rgba(255,255,255,0.75)",
            backdropFilter: "blur(14px)",
            border: "1px solid rgba(0,0,0,0.06)",
            boxShadow: "0 20px 60px rgba(0,0,0,0.08)",
            transition: "all 0.3s ease",
            transform: dragActive ? "scale(1.02)" : "scale(1)"
          }}
        >
          {/* Glow accent */}
          <Box
            sx={{
              position: "absolute",
              top: -80,
              right: -80,
              width: 180,
              height: 180,
              background: "radial-gradient(circle, #93c5fd, transparent 60%)",
              filter: "blur(20px)"
            }}
          />

          {/* Header */}
          <Typography
            variant="h4"
            sx={{
              fontWeight: 600,
              letterSpacing: "-0.02em",
              mb: 1
            }}
          >
            Upload a document
          </Typography>

          <Typography
            variant="body2"
            sx={{
              color: "text.secondary",
              mb: 4
            }}
          >
            Drop a file or select one to begin analysis
          </Typography>

          {/* Dropzone */}
          <Box
            onClick={() => inputRef.current?.click()}
            sx={{
              borderRadius: 4,
              border: "1.5px dashed",
              borderColor: dragActive ? "#60a5fa" : "rgba(0,0,0,0.15)",
              p: 4,
              textAlign: "center",
              cursor: "pointer",
              transition: "all 0.2s ease",
              background: dragActive
                ? "rgba(96,165,250,0.08)"
                : "rgba(255,255,255,0.5)",
              "&:hover": {
                borderColor: "#60a5fa",
                background: "rgba(96,165,250,0.06)"
              }
            }}
          >
            <Typography sx={{ fontWeight: 500, mb: 1 }}>
              Drag & drop your file here
            </Typography>

            <Typography variant="body2" sx={{ color: "text.secondary" }}>
              or click to browse (.txt supported)
            </Typography>

            <input
              ref={inputRef}
              type="file"
              hidden
              accept=".txt"
              onChange={(e) => onFileSelect(e.target.files[0])}
            />
          </Box>

          {/* File preview */}
          {file && (
            <Box
              sx={{
                mt: 3,
                p: 2,
                borderRadius: 3,
                background: "rgba(15,23,42,0.04)",
                border: "1px solid rgba(0,0,0,0.06)"
              }}
            >
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                Selected file
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary" }}>
                {file.name}
              </Typography>
            </Box>
          )}

          {/* CTA */}
          <Box sx={{ mt: 4, display: "flex", justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              onClick={handleUpload}
              disabled={!file || loading}
              sx={{
                px: 3,
                py: 1.2,
                borderRadius: 3,
                textTransform: "none",
                fontWeight: 600,
                background: "linear-gradient(135deg, #60a5fa, #6366f1)",
                boxShadow: "0 10px 30px rgba(99,102,241,0.25)",
                "&:hover": {
                  background: "linear-gradient(135deg, #3b82f6, #4f46e5)"
                }
              }}
            >
              {loading ? "Uploading..." : "Upload & Create Run"}
            </Button>
          </Box>
        </Paper>
      </Fade>
    </Box>
  )
}