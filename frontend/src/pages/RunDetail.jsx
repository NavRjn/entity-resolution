import { useParams } from "react-router-dom"
import { useEffect, useState } from "react"

export default function RunDetail() {
  const { runId } = useParams()
  const [data, setData] = useState(null)

  useEffect(() => {
    fetch(`http://localhost:8000/api/runs/${runId}`)
      .then(r => r.json())
      .then(setData)
  }, [runId])

  if (!data) return <div>Loading...</div>

  return (
    <div>
      <h1>Run {runId}</h1>

      <h2>Entities</h2>
      <pre>{JSON.stringify(data.entities, null, 2)}</pre>

      <h2>Relationships</h2>
      <pre>{JSON.stringify(data.relationships, null, 2)}</pre>
    </div>
  )
}