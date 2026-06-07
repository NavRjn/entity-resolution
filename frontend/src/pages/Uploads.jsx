import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  Box,
  Typography,
  Button,
  List,
  ListItem,
  ListItemText,
  Divider
} from "@mui/material"

export default function Uploads() {
  const [uploads, setUploads] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    async function fetchUploads() {
      try {
        const resp = await fetch("http://localhost:8000/api/uploads")
        const data = await resp.json()
        console.log("Uploads response:", data)
        setUploads(Array.isArray(data) ? data : data.uploads || [])
      } catch (err) {
        console.error(err)
      }
    }
    fetchUploads()
  }, [])

  async function handleCreateRun(uploadId) {
    try {
      const resp = await fetch("http://localhost:8000/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId })
      })
      const data = await resp.json()
      navigate(`/runs/${data.run_id}`)
    } catch (err) {
      console.error(err)
    }
  }

  console.log(uploads)

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        Uploads
      </Typography>

      <Button
        variant="contained"
        color="primary"
        sx={{ mb: 2 }}
        onClick={() => navigate("/uploads/new")}
      >
        Upload New File
      </Button>

      <List>
        {uploads.map((u) => (
          <div key={u.upload_id}>
            <ListItem
              secondaryAction={
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => handleCreateRun(u.upload_id)}
                >
                  Create Run
                </Button>
              }
            >
              <ListItemText
                primary={u.filename}
                secondary={`${new Date(
                  u.uploaded_at
                ).toLocaleString()}`}
              />
            </ListItem>
            <Divider />
          </div>
        ))}
      </List>
    </Box>
  )
}