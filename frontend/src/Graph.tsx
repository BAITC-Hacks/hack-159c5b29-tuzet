import { useEffect, useRef, type MutableRefObject } from "react";
import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from "cytoscape";
import type { Edge, Node } from "./api";

function graphColors() {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return {
    role: Object.fromEntries(["consolidator", "distributor", "transit", "coordinator", "terminal", "peripheral"].map(role => [role, token(`--role-${role}`)])),
    clusters: ["--accent", "--cyan", "--purple", "--green", "--warn", "--red"].map(token),
    text: token("--text"), line: token("--muted"), accent: token("--accent"), warn: token("--warn"), graph: token("--graph"),
  };
}

export function uniqueSuffixLabels(gids: string[]): Map<string, string> {
  const labels = new Map<string, string>();
  for (const gid of gids) {
    let length = Math.min(6, gid.length);
    while (length < gid.length) {
      const suffix = gid.slice(-length);
      if (gids.filter((other) => other.endsWith(suffix)).length === 1) break;
      length += 1;
    }
    labels.set(gid, gid.slice(-length));
  }
  return labels;
}

export type GraphViewport = { zoom: number; pan: { x: number; y: number } };
export interface GraphProps { nodes: Node[]; edges: Edge[]; selected?: string; onSelect: (gid: string) => void; onEdge: (edge: Edge) => void; colorBy: "role" | "cluster"; theme: "dark" | "light"; viewportRef: MutableRefObject<GraphViewport | null>; centeredRef: MutableRefObject<string | undefined> }
export function Graph({ nodes, edges, selected, onSelect, onEdge, colorBy, theme, viewportRef, centeredRef }: Readonly<GraphProps>) {
  const ref = useRef<HTMLDivElement>(null);
  const core = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  const onEdgeRef = useRef(onEdge);
  useEffect(() => { onSelectRef.current = onSelect; onEdgeRef.current = onEdge; }, [onSelect, onEdge]);
  useEffect(() => {
    if (!ref.current) return;
    const showLabels = nodes.length <= 50;
    const labels = uniqueSuffixLabels(nodes.map((node) => node.gid));
    const colors = graphColors();
    const graph = cytoscape({
      container: ref.current,
      elements: [
        ...nodes.map((node) => ({ data: { id: node.gid, label: labels.get(node.gid), role: node.role, cluster: node.cluster_id, seed: node.is_seed, boundary: node.depth === 4 } })),
        ...edges.map((edge, index) => ({ data: { id: `${edge.source}-${edge.target}-${index}`, ...edge } })),
      ],
      style: [
        { selector: "node", style: { label: showLabels ? "data(label)" : "", color: colors.text, "font-size": "10px", "text-valign": "bottom", "text-margin-y": 4, width: 28, height: 28, "background-color": (node: NodeSingular) => colorBy === "role" ? colors.role[String(node.data("role"))] ?? colors.line : colors.clusters[Number(node.data("cluster")) % colors.clusters.length], "border-width": (node: NodeSingular) => node.data("seed") ? 4 : 0, "border-color": colors.warn, shape: (node: NodeSingular) => node.data("boundary") ? "diamond" : "ellipse" } },
        { selector: "node:selected", style: { label: "data(label)", width: 38, height: 38, "border-width": 4, "border-color": colors.accent } },
        { selector: "edge", style: { width: (edge: EdgeSingular) => Math.max(1, Math.min(6, Math.log10(Number(edge.data("sum_kzt")) + 1) - 2)), "line-color": colors.line, "target-arrow-color": colors.line, "target-arrow-shape": "triangle", "curve-style": "bezier", opacity: 0.8 } },
      ],
      layout: { name: "cose", animate: false, padding: 28 },
    });
    core.current = graph;
    if (viewportRef.current) graph.viewport(viewportRef.current);
    graph.on("tap", "node", (event) => onSelectRef.current(event.target.id()));
    graph.on("tap", "edge", (event) => onEdgeRef.current(event.target.data() as Edge));
    return () => { viewportRef.current = { zoom: graph.zoom(), pan: graph.pan() }; graph.destroy(); core.current = null; };
  }, [nodes, edges, viewportRef]);
  useEffect(() => {
    const graph = core.current;
    if (!graph) return;
    const colors = graphColors();
    graph.batch(() => graph.nodes().forEach((node) => {
      node.style("background-color", colorBy === "role"
        ? colors.role[String(node.data("role"))] ?? colors.line
        : colors.clusters[Number(node.data("cluster")) % colors.clusters.length]);
      node.style("color", colors.text);
    }));
    graph.edges().style({ "line-color": colors.line, "target-arrow-color": colors.line });
  }, [colorBy, theme, nodes, edges]);
  useEffect(() => {
    const graph = core.current;
    if (!graph || !selected) return;
    graph.nodes().unselect();
    const target = graph.getElementById(selected);
    if (target.length) {
      target.select();
      if (centeredRef.current !== selected) graph.center(target);
    }
    centeredRef.current = selected;
  }, [selected, nodes, edges]);
  return <div className="network" ref={ref} aria-label="Направленный граф переводов" />;
}
