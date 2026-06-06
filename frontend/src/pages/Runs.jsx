import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

export default function Runs() {
  const [runs, setRuns] = useState([])

  useEffect(() => {
    fetch("http://localhost:8000/api/runs")
      .then(r => r.json())
      .then(setRuns)
  }, [])

  return (
    <div>
      <h1>Runs</h1>

      <pre>{JSON.stringify(runs, null, 2)}</pre>

      <ul>
        {runs.map(r => (
          <li key={r.run_id}>
            <Link to={`/runs/${r.run_id}`}>
              {r.run_id}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}