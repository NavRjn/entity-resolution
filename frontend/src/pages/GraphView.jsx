import { useEffect, useState, useRef } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { useParams, useNavigate } from "react-router-dom"
import { Box, Typography } from "@mui/material"

export default function GraphView() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const fgRef = useRef()

  const [graph, setGraph] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)

  // --- COLOR MAPS ---
  const nodeColors = {
    person: "#2d3436",
    company: "#0984e3",
    location: "#00b894",
    default: "#636e72",
  }

  const edgeColors = {
    works_at: "#6c5ce7",
    owns: "#e17055",
    related_to: "#636e72",
    default: "#b2bec3",
  }

  useEffect(() => {
    async function loadGraph() {
      try {
        const resp = await fetch(`http://localhost:8000/api/runs/${runId}/graph`)
        const data = await resp.json()

        setGraph({
          nodes: Array.isArray(data.nodes) ? data.nodes : [],
          links: Array.isArray(data.edges)
            ? data.edges.map(e => ({
                source: e.source,
                target: e.target,
                type: e.relationship_type || "default"
              }))
            : []
        })
      } catch (err) {
        console.error(err)
        setGraph({ nodes: [], links: [] })
      } finally {
        setLoading(false)
      }
    }

    loadGraph()
  }, [runId])

  // IMPORTANT: fix "half graph invisible" issue
  useEffect(() => {
    if (!loading && fgRef.current) {
      setTimeout(() => {
        fgRef.current.zoomToFit(500, 80) // padding fixes clipping
      }, 300)
    }
  }, [loading])

  if (loading) {
    return (
      <Box sx={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Typography>Loading graph...</Typography>
      </Box>
    )
  }

  return (
    <div
      style={{
        height: "100vh",
        width: "100%",
        backgroundColor: "#f7f9fc"
      }}
    >
      {/* LEGEND */}
      <div style={{
        position: "absolute",
        top: 10,
        left: 10,
        background: "white",
        padding: 12,
        borderRadius: 8,
        fontSize: 12,
        zIndex: 10,
        boxShadow: "0 2px 10px rgba(0,0,0,0.1)"
      }}>
        <div><b>Node Types</b></div>
        <div>● Person</div>
        <div>● Company</div>
        <div>● Location</div>

        <div style={{ marginTop: 8 }}><b>Edges</b></div>
        <div>— works_at</div>
        <div>— owns</div>
        <div>— related_to</div>
      </div>

      <ForceGraph2D
        ref={fgRef}
        graphData={graph}

        // --- LAYOUT FIXES ---
        d3VelocityDecay={0.35}
        d3AlphaDecay={0.02}

        // --- EDGES ---
        linkWidth={1.2}
        linkDirectionalArrowLength={5}
        linkDirectionalArrowRelPos={1}
        linkColor={link => edgeColors[link.type] || edgeColors.default}

        // softer motion (less aggressive)
        linkDirectionalParticles={1}
        linkDirectionalParticleSpeed={0.003}

        // --- NODE SIZE (BIG CHANGE) ---
        nodeVal={node => {
          // bigger nodes
          if (node.entity_type === "company") return 20
          if (node.entity_type === "person") return 15
          return 10
        }}

        // --- CLICK ---
        onNodeClick={(node) => {
          navigate(
            `/runs/${runId}/document?entity=${encodeURIComponent(node.label || node.id)}`
          )
        }}

        // --- NODE DRAW ---
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.label || node.id
          const type = node.entity_type || "default"

          const radius =
            type === "company" ? 7 :
            type === "person" ? 6 :
            5

          // NODE BODY (dark but color-coded)
          ctx.beginPath()
          ctx.fillStyle = nodeColors[type] || nodeColors.default
          ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
          ctx.fill()

          // subtle border glow
          ctx.strokeStyle = "rgba(0,0,0,0.15)"
          ctx.lineWidth = 1
          ctx.stroke()

          // LABEL (dark readable text)
          const fontSize = 12 / globalScale
          ctx.font = `${fontSize}px Sans-Serif`
          ctx.fillStyle = "#2c3e50"
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"

          ctx.fillText(label, node.x, node.y + radius + 10)
        }}
      />
    </div>
  )
}