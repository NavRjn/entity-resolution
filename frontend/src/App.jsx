import { Routes, Route, Link } from "react-router-dom"

import Runs from "./pages/Runs.jsx"
import RunDetail from "./pages/RunDetail.jsx"
import RunCreating from "./pages/RunCreating.jsx"
import Uploads from "./pages/Uploads.jsx"
import UploadNew from "./pages/UploadNew.jsx"
import Relationships from "./pages/Relationships.jsx"
import Document from "./pages/Document.jsx"

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
          <Route path="/runs/creating" element={<RunCreating />} />

          <Route path="/uploads" element={<Uploads />} />
          <Route path="/uploads/new" element={<UploadNew />} />
          <Route path="/runs/:runId/relationships" element={<Relationships />} />
          <Route path="/runs/:runId/document" element={<Document />} />
      </Routes>
    </div>
  )
}