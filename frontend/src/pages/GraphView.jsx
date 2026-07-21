import { useEffect, useState, useRef } from "react"
import ForceGraph2D from "react-force-graph-2d"
import { useParams, useNavigate } from "react-router-dom"
import { Box, Typography } from "@mui/material"
import * as d3 from "d3-force"

export default function GraphView() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const fgRef = useRef()

  const [graph, setGraph] = useState({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [hoverNode, setHoverNode] = useState(null)

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

  /* ---------------- LOAD ---------------- */

  useEffect(() => {
    async function loadGraph() {
      try {
        const resp = await fetch(`http://localhost:8000/api/runs/${runId}/graph`)
        const data = await resp.json()

        setGraph({
          nodes: data.nodes || [],
          links: (data.edges || []).map(e => ({
            source: e.source,
            target: e.target,
            type: e.relationship_type || "default"
          }))
        })
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    loadGraph()
  }, [runId])

  /* ---------------- FORCE ENGINE (SAFE VERSION) ---------------- */

  useEffect(() => {
    if (!fgRef.current || loading) return

    const fg = fgRef.current

    // stronger structure
    fg.d3Force("charge", d3.forceManyBody().strength(-220))

    fg.d3Force("link")
      .distance(80)
      .strength(0.7)

    // ✅ REAL collision (no require, no crash)
    fg.d3Force(
      "collision",
      d3.forceCollide().radius(node => {
        const base =
          node.entity_type === "company" ? 26 :
          node.entity_type === "person" ? 22 :
          node.entity_type === "case" ? 24 : 18

        return base + 6
      })
    )

    setTimeout(() => {
      fg.zoomToFit(600, 120)
    }, 500)
  }, [loading])

  /* ---------------- HELPERS ---------------- */

  const getLabel = (node, globalScale) => {
    const full = node.label || node.id

    if (globalScale < 0.7) {
      return full
        .split(" ")
        .map(w => w[0])
        .join("")
        .slice(0, 3)
        .toUpperCase()
    }

    return full
  }

  const getRadius = (node) => {
    return (
      node.entity_type === "company" ? 18 :
      node.entity_type === "person" ? 16 :
      node.entity_type === "case" ? 18 : 14
    )
  }

  const isDenseMode = false // keep stable first (IMPORTANT for debugging)

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
        background: "#f8fafc",
        overflow: "hidden"
      }}
    >

      <ForceGraph2D
        ref={fgRef}
        graphData={graph}

        /* layout stability */
        d3VelocityDecay={0.35}
        d3AlphaDecay={0.02}

        /* links */
        linkWidth={1.5}
        linkColor={l => edgeColors[l.type] || edgeColors.default}
        linkDirectionalArrowLength={6}
        linkDirectionalArrowRelPos={1}
        linkCurvature={0.25}

        /* interaction */
        onNodeHover={setHoverNode}

        onNodeClick={(node) => {
          navigate(
            `/runs/${runId}/document?entity=${encodeURIComponent(
              node.label || node.id
            )}`
          )
        }}

        /* node size */
        nodeVal={getRadius}

        /* IMPORTANT: correct rendering */
        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = getLabel(node, globalScale)
          const type = node.entity_type || "default"
          const radius = getRadius(node)

          const isHovered = hoverNode?.id === node.id

          ctx.globalAlpha = isHovered ? 1 : 0.9

          /* node */
          ctx.beginPath()
          ctx.fillStyle = nodeColors[type] || nodeColors.default
          ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
          ctx.fill()

          ctx.strokeStyle = "rgba(0,0,0,0.1)"
          ctx.stroke()

          /* label */
          const fontSize = Math.max(10 / globalScale, 7)
          ctx.font = `${fontSize}px Sans-Serif`
          ctx.fillStyle = "#1f2937"
          ctx.textAlign = "center"
          ctx.textBaseline = "middle"

          ctx.fillText(label, node.x, node.y + radius + 10)

          ctx.globalAlpha = 1
        }}
      />
    </div>
  )
}