import { Routes, Route, Link } from "react-router-dom"

import Runs from "./pages/Runs.jsx"
import RunDetail from "./pages/RunDetail.jsx"
import Uploads from "./pages/Uploads.jsx"
import UploadNew from "./pages/UploadNew.jsx"

export default function App() {
  return (
    <div style={{ padding: 20 }}>
      <nav style={{ marginBottom: 20 }}>
        <Link to="/runs">Runs</Link> |{" "}
        <Link to="/uploads">Uploads</Link> |{" "}
        <Link to="/uploads/new">Upload New</Link>
      </nav>

      <Routes>
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:runId" element={<RunDetail />} />

        <Route path="/uploads" element={<Uploads />} />
        <Route path="/uploads/new" element={<UploadNew />} />
      </Routes>
    </div>
  )
}