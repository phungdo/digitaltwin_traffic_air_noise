import { useState } from "react";

const nodes = [
  {
    id: "main",
    label: "main()",
    desc: "Entry point — orchestrates the full pipeline",
    x: 400, y: 40,
    w: 220, h: 52,
    type: "entry",
    details: [
      "Creates output directory",
      "Initializes logging (console + file)",
      "Creates HTTP session with custom User-Agent",
      "Calls pipeline stages sequentially",
      "Prints summary stats at the end",
    ],
  },
  {
    id: "logging",
    label: "setup_logging()",
    desc: "Console + file logger → download.log",
    x: 120, y: 140,
    w: 200, h: 48,
    type: "util",
    details: [
      "Logger name: 'madrid_traffic'",
      "Console handler: INFO level",
      "File handler: DEBUG level → download.log",
      "Format: timestamp | level | message",
    ],
  },
  {
    id: "discover",
    label: "fetch_csv_links()",
    desc: "Scrape catalog page → list of CSV URLs + year/month",
    x: 400, y: 150,
    w: 240, h: 52,
    type: "core",
    details: [
      "GET datos.madrid.es/.../downloads",
      "Regex 1: find all CSV href patterns",
      "  → /dataset/300233-.../download/*.csv",
      "Regex 2: look backwards ≤2000 chars from each href",
      "  → extract 'YYYY. Mes' (e.g. '2025. Enero')",
      "Map Spanish month → English 3-letter abbreviation",
      "Sort results by (year, month)",
      `Returns: [{url, year, month_en}, ...]`,
    ],
  },
  {
    id: "loop",
    label: "for each CSV file",
    desc: "Iterate over discovered files",
    x: 400, y: 270,
    w: 220, h: 48,
    type: "control",
    details: [
      "Filename: {YYYY}_{Mon}_aforo_trafico.csv",
      "Skip if file already exists & non-empty",
      "Track stats: downloaded / skipped / failed / invalid",
      "Polite 1-second delay between downloads",
    ],
  },
  {
    id: "skip",
    label: "Already exists?",
    desc: "Skip download if file is present",
    x: 140, y: 340,
    w: 180, h: 44,
    type: "decision",
    details: [
      "Check: os.path.isfile(dest) and size > 0",
      "If yes → stats['skipped'] += 1, continue",
      "If no → proceed to download",
    ],
  },
  {
    id: "download",
    label: "download_file()",
    desc: "GET with retries (max 3) → stream to disk",
    x: 400, y: 380,
    w: 220, h: 52,
    type: "core",
    details: [
      "Up to 3 retry attempts",
      "5-second delay between retries",
      "60-second request timeout",
      "Streams response in 8KB chunks",
      "Returns True on success, False on failure",
    ],
  },
  {
    id: "validate",
    label: "validate_csv()",
    desc: "Check file integrity: size, delimiters, line count",
    x: 400, y: 490,
    w: 220, h: 52,
    type: "core",
    details: [
      "✓ File exists and non-empty",
      "⚠ Warn if < 500 bytes (suspiciously small)",
      "✓ First line contains ';' or ',' delimiter",
      "✓ At least 2 lines (header + data)",
      "Logs: filename, line count, file size in KB",
    ],
  },
  {
    id: "md5",
    label: "compute_md5()",
    desc: "Hash for integrity tracking",
    x: 680, y: 490,
    w: 180, h: 48,
    type: "util",
    details: [
      "Reads file in 8KB chunks",
      "Computes MD5 hexdigest",
      "Logged at DEBUG level",
    ],
  },
  {
    id: "summary",
    label: "Summary Report",
    desc: "Print stats: downloaded / skipped / failed / invalid",
    x: 400, y: 600,
    w: 220, h: 48,
    type: "output",
    details: [
      "Total elapsed time in seconds",
      "Count: downloaded, skipped, failed, invalid",
      "Output directory path",
    ],
  },
  {
    id: "disk",
    label: "~/Downloads/.../traffic_csv/",
    desc: "YYYY_Mon_aforo_trafico.csv files",
    x: 680, y: 380,
    w: 220, h: 48,
    type: "output",
    details: [
      "Path: ~/Downloads/madrid_traffic_airquality/",
      "        traffic_datasets/traffic_csv/",
      "Example files:",
      "  2018_Jan_aforo_trafico.csv",
      "  2025_Dec_aforo_trafico.csv",
      "  download.log",
    ],
  },
];

const edges = [
  { from: "main", to: "logging", label: "1" },
  { from: "main", to: "discover", label: "2" },
  { from: "discover", to: "loop", label: "3" },
  { from: "loop", to: "skip", label: "4" },
  { from: "skip", to: "download", label: "new file" },
  { from: "download", to: "validate", label: "5" },
  { from: "validate", to: "md5", label: "if valid" },
  { from: "download", to: "disk", label: "write", dashed: true },
  { from: "loop", to: "summary", label: "done" },
];

const typeColors = {
  entry: { bg: "#1a1a2e", border: "#e94560", text: "#e94560", glow: "rgba(233,69,96,0.3)" },
  core: { bg: "#16213e", border: "#0f9b8e", text: "#5eead4", glow: "rgba(15,155,142,0.25)" },
  util: { bg: "#1a1a2e", border: "#6366f1", text: "#a5b4fc", glow: "rgba(99,102,241,0.2)" },
  control: { bg: "#1a1a2e", border: "#f59e0b", text: "#fcd34d", glow: "rgba(245,158,11,0.25)" },
  decision: { bg: "#1a1a2e", border: "#f59e0b", text: "#fcd34d", glow: "rgba(245,158,11,0.2)" },
  output: { bg: "#1a1a2e", border: "#22d3ee", text: "#67e8f9", glow: "rgba(34,211,238,0.2)" },
};

function getCenter(node) {
  return { x: node.x + node.w / 2, y: node.y + node.h / 2 };
}

function getEdgePath(fromNode, toNode) {
  const f = getCenter(fromNode);
  const t = getCenter(toNode);
  const dx = t.x - f.x;
  const dy = t.y - f.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist === 0) return { x1: f.x, y1: f.y, x2: t.x, y2: t.y };

  const margin = 4;
  const fx = f.x + (dx / dist) * (fromNode.w / 2 + margin) * (Math.abs(dx) > Math.abs(dy) ? 1 : 0.3);
  const fy = f.y + (dy / dist) * (fromNode.h / 2 + margin) * (Math.abs(dy) >= Math.abs(dx) ? 1 : 0.3);
  const tx = t.x - (dx / dist) * (toNode.w / 2 + margin) * (Math.abs(dx) > Math.abs(dy) ? 1 : 0.3);
  const ty = t.y - (dy / dist) * (toNode.h / 2 + margin) * (Math.abs(dy) >= Math.abs(dx) ? 1 : 0.3);

  return { x1: fx, y1: fy, x2: tx, y2: ty };
}

export default function FlowDiagram() {
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);

  const selectedNode = nodes.find((n) => n.id === selected);

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0d1117",
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
      color: "#c9d1d9",
      padding: "24px",
      boxSizing: "border-box",
    }}>
      <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600&display=swap" rel="stylesheet" />
      
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 24, borderBottom: "1px solid #21262d", paddingBottom: 16 }}>
          <h1 style={{
            fontSize: 18,
            fontWeight: 600,
            color: "#e94560",
            margin: 0,
            letterSpacing: "0.05em",
          }}>
            download_madrid_traffic.py
          </h1>
          <p style={{ fontSize: 11, color: "#484f58", margin: "6px 0 0", lineHeight: 1.5 }}>
            Flow diagram — click any node for details
          </p>
        </div>

        <div style={{ display: "flex", gap: 20 }}>
          {/* SVG Diagram */}
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
            <svg
              viewBox="0 0 920 680"
              style={{
                width: "100%",
                height: "auto",
                background: "#0d1117",
                borderRadius: 8,
                border: "1px solid #21262d",
              }}
            >
              <defs>
                <marker id="arrow" viewBox="0 0 10 7" refX="9" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 3.5 L 0 7 z" fill="#484f58" />
                </marker>
                <marker id="arrow-hi" viewBox="0 0 10 7" refX="9" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 3.5 L 0 7 z" fill="#5eead4" />
                </marker>
                {/* Grid pattern */}
                <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#161b22" strokeWidth="0.5" />
                </pattern>
              </defs>

              <rect width="920" height="680" fill="url(#grid)" />

              {/* Edges */}
              {edges.map((edge, i) => {
                const fromNode = nodes.find((n) => n.id === edge.from);
                const toNode = nodes.find((n) => n.id === edge.to);
                if (!fromNode || !toNode) return null;
                const p = getEdgePath(fromNode, toNode);
                const mx = (p.x1 + p.x2) / 2;
                const my = (p.y1 + p.y2) / 2;
                const isHighlighted = selected === edge.from || selected === edge.to;

                return (
                  <g key={i}>
                    <line
                      x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2}
                      stroke={isHighlighted ? "#5eead4" : "#30363d"}
                      strokeWidth={isHighlighted ? 1.5 : 1}
                      strokeDasharray={edge.dashed ? "6,4" : "none"}
                      markerEnd={isHighlighted ? "url(#arrow-hi)" : "url(#arrow)"}
                      opacity={isHighlighted ? 1 : 0.6}
                    />
                    {edge.label && (
                      <text
                        x={mx} y={my - 5}
                        textAnchor="middle"
                        fontSize="9"
                        fill={isHighlighted ? "#5eead4" : "#484f58"}
                        fontFamily="inherit"
                      >
                        {edge.label}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Nodes */}
              {nodes.map((node) => {
                const colors = typeColors[node.type];
                const isSelected = selected === node.id;
                const isHovered = hovered === node.id;

                return (
                  <g
                    key={node.id}
                    style={{ cursor: "pointer" }}
                    onClick={() => setSelected(isSelected ? null : node.id)}
                    onMouseEnter={() => setHovered(node.id)}
                    onMouseLeave={() => setHovered(null)}
                  >
                    {(isSelected || isHovered) && (
                      <rect
                        x={node.x - 3} y={node.y - 3}
                        width={node.w + 6} height={node.h + 6}
                        rx={10} ry={10}
                        fill="none"
                        stroke={colors.border}
                        strokeWidth={1}
                        opacity={0.4}
                      />
                    )}
                    <rect
                      x={node.x} y={node.y}
                      width={node.w} height={node.h}
                      rx={7} ry={7}
                      fill={isSelected ? colors.border + "18" : colors.bg}
                      stroke={colors.border}
                      strokeWidth={isSelected ? 2 : 1}
                      opacity={isSelected ? 1 : isHovered ? 0.95 : 0.85}
                    />
                    <text
                      x={node.x + node.w / 2}
                      y={node.y + 20}
                      textAnchor="middle"
                      fontSize="12"
                      fontWeight="500"
                      fill={colors.text}
                      fontFamily="inherit"
                    >
                      {node.label}
                    </text>
                    <text
                      x={node.x + node.w / 2}
                      y={node.y + 35}
                      textAnchor="middle"
                      fontSize="9"
                      fill="#6e7681"
                      fontFamily="inherit"
                    >
                      {node.desc.length > 40 ? node.desc.slice(0, 38) + "…" : node.desc}
                    </text>
                  </g>
                );
              })}

              {/* Legend */}
              {[
                { type: "core", label: "Core logic" },
                { type: "util", label: "Utility" },
                { type: "control", label: "Control flow" },
                { type: "output", label: "Output" },
              ].map((item, i) => (
                <g key={item.type} transform={`translate(20, ${610 + i * 16})`}>
                  <rect width={10} height={10} rx={2} fill={typeColors[item.type].border} opacity={0.7} />
                  <text x={16} y={9} fontSize="9" fill="#6e7681" fontFamily="inherit">{item.label}</text>
                </g>
              ))}
            </svg>
          </div>

          {/* Detail Panel */}
          <div style={{
            width: 260,
            flexShrink: 0,
            background: "#161b22",
            borderRadius: 8,
            border: "1px solid #21262d",
            padding: 16,
            alignSelf: "flex-start",
            position: "sticky",
            top: 24,
          }}>
            {selectedNode ? (
              <>
                <div style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: typeColors[selectedNode.type].text,
                  marginBottom: 4,
                }}>
                  {selectedNode.label}
                </div>
                <div style={{
                  fontSize: 10,
                  color: "#8b949e",
                  marginBottom: 14,
                  lineHeight: 1.5,
                }}>
                  {selectedNode.desc}
                </div>
                <div style={{
                  borderTop: "1px solid #21262d",
                  paddingTop: 12,
                }}>
                  {selectedNode.details.map((line, i) => (
                    <div key={i} style={{
                      fontSize: 10,
                      color: line.startsWith("✓") ? "#5eead4" :
                             line.startsWith("⚠") ? "#fcd34d" :
                             line.startsWith("→") || line.startsWith("  →") ? "#a5b4fc" :
                             "#8b949e",
                      marginBottom: 5,
                      lineHeight: 1.5,
                      paddingLeft: line.startsWith("  ") ? 10 : 0,
                      fontFamily: "inherit",
                    }}>
                      {line}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 11, color: "#484f58", lineHeight: 1.7 }}>
                <div style={{ marginBottom: 12, color: "#6e7681" }}>Click a node to see details</div>
                <div style={{ borderTop: "1px solid #21262d", paddingTop: 12 }}>
                  <div style={{ color: "#8b949e", marginBottom: 8, fontWeight: 500 }}>Pipeline stages:</div>
                  <div style={{ color: "#6e7681" }}>1. Initialize logging</div>
                  <div style={{ color: "#6e7681" }}>2. Scrape catalog for CSV links</div>
                  <div style={{ color: "#6e7681" }}>3. Parse year/month from HTML</div>
                  <div style={{ color: "#6e7681" }}>4. Download each file (with retry)</div>
                  <div style={{ color: "#6e7681" }}>5. Validate CSV structure</div>
                  <div style={{ color: "#6e7681" }}>6. Compute MD5 checksum</div>
                  <div style={{ color: "#6e7681" }}>7. Print summary report</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
