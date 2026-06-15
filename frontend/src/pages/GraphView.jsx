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
  const [hoverNode, setHoverNode] = useState(null)

  /* ---------------- COLORS (SOFT LEGAL PALETTE) ---------------- */

  const nodeColors = {
    person: "#4f46e5",
    company: "#0ea5e9",
    location: "#10b981",
    case: "#f59e0b",
    default: "#64748b"
  }

  const edgeColors = {
    works_at: "#6366f1",
    owns: "#f97316",
    related_to: "#94a3b8",
    cites: "#22c55e",
    default: "#cbd5e1"
  }

  /* ---------------- LOAD GRAPH ---------------- */

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

  /* ---------------- AUTO-FIT ---------------- */

  useEffect(() => {
    if (!loading && fgRef.current) {
      setTimeout(() => {
        fgRef.current.zoomToFit(600, 120)
      }, 400)
    }
  }, [loading])

  if (loading) {
    return (
      <Box sx={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#f8fafc"
      }}>
        <Typography sx={{ color: "#64748b" }}>
          Loading legal relationship graph...
        </Typography>
      </Box>
    )
  }

  return (
    <div
      style={{
        height: "100vh",
        width: "100%",
        background: `
          radial-gradient(circle at 20% 10%, #eef2ff 0%, transparent 40%),
          radial-gradient(circle at 80% 30%, #ecfeff 0%, transparent 45%),
          radial-gradient(circle at 40% 80%, #fef3c7 0%, transparent 45%),
          #f8fafc
        `,
        overflow: "hidden"
      }}
    >

      {/* FLOATING LEGEND */}
      <div
        style={{
          position: "absolute",
          top: 16,
          left: 16,
          zIndex: 10,
          padding: 14,
          borderRadius: 14,
          background: "rgba(255,255,255,0.75)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(0,0,0,0.06)",
          boxShadow: "0 10px 30px rgba(0,0,0,0.08)",
          fontSize: 12,
          color: "#334155",
          width: 180
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Entities</div>
        <div>● Person</div>
        <div>● Company</div>
        <div>● Location</div>
        <div>● Case</div>

        <div style={{ marginTop: 10, fontWeight: 600 }}>Relations</div>
        <div>→ works at</div>
        <div>→ owns</div>
        <div>→ cites</div>
      </div>

      <ForceGraph2D
        ref={fgRef}
        graphData={graph}

        /* ---------------- LAYOUT (LESS CHAOS) ---------------- */
        d3VelocityDecay={0.4}
        d3AlphaDecay={0.03}
        d3Force="link"
        d3ForceConfig={{
          link: { distance: 140 }
        }}

        /* ---------------- LINKS (FLOW STYLE) ---------------- */
        linkWidth={1.6}
        linkColor={l => edgeColors[l.type] || edgeColors.default}
        linkDirectionalArrowLength={6}
        linkDirectionalArrowRelPos={1}
        linkCurvature={0.25}

        /* subtle motion */
        linkDirectionalParticles={hoverNode ? 0 : 1}
        linkDirectionalParticleSpeed={0.004}

        /* ---------------- NODE SIZE ---------------- */
        nodeVal={node => {
          if (node.entity_type === "company") return 28
          if (node.entity_type === "person") return 22
          if (node.entity_type === "case") return 26
          return 18
        }}

        /* ---------------- INTERACTION ---------------- */
        onNodeHover={setHoverNode}

        onNodeClick={(node) => {
          navigate(
            `/runs/${runId}/document?entity=${encodeURIComponent(
              node.label || node.id
            )}`
          )
        }}

        /* ---------------- CUSTOM NODE RENDER ---------------- */
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.label || node.id
          const type = node.entity_type || "default"

          const baseRadius =
            type === "company" ? 18 :
            type === "person" ? 16 :
            type === "case" ? 18 : 14

          const isHovered = hoverNode && hoverNode.id === node.id

          const radius = isHovered ? baseRadius + 6 : baseRadius

          /* --- NODE BACKGROUND (PILL STYLE) --- */
          ctx.beginPath()
          ctx.fillStyle = nodeColors[type] || nodeColors.default

          // rounded pill shape
          const w = ctx.measureText(label).width / globalScale + 30
          const h = 26

          const x = node.x - w / 2
          const y = node.y - h / 2

          const r = 10

          ctx.moveTo(x + r, y)
          ctx.lineTo(x + w - r, y)
          ctx.quadraticCurveTo(x + w, y, x + w, y + r)
          ctx.lineTo(x + w, y + h - r)
          ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
          ctx.lineTo(x + r, y + h)
          ctx.quadraticCurveTo(x, y + h, x, y + h - r)
          ctx.lineTo(x, y + r)
          ctx.quadraticCurveTo(x, y, x + r, y)
          ctx.closePath()
          ctx.fill()

          /* subtle glow */
          ctx.strokeStyle = "rgba(0,0,0,0.08)"
          ctx.stroke()

          /* --- TEXT INSIDE NODE --- */
          ctx.font = `${12 / globalScale}px Sans-Serif`
          ctx.fillStyle = "white"
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"

          ctx.fillText(label, node.x, node.y)
        }}
      />
    </div>
  )
}