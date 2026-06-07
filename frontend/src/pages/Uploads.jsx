import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

export default function Uploads() {
  const [uploads, setUploads] = useState([])

  useEffect(() => {
    fetch("http://localhost:8000/api/uploads")
      .then(r => r.json())
      .then(setUploads)
  }, [])

  return (
    <div>
      <h1>Uploads</h1>

      <pre>{JSON.stringify(uploads, null, 2)}</pre>

      <ul>
        {uploads.map(r => (
          <li key={r.upload_id}>
            <Link to={`/uploads/${r.upload_id}`}>
              {r.upload_id}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}