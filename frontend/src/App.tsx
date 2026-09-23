import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson, type Cluster, type Disruption, type Edge, type Motif, type Neighborhood, type Node, type Sensitivity, type Summary, type Transaction, type Wrapped } from "./api";
import type { GraphViewport } from "./Graph";
import { Shell } from "./components/Shell";
import { Status } from "./components/UI";
import { type View } from "./data/ui";
import { OverviewPage, RunPage, AssistantPage } from "./pages/InfoPages";
import { GraphPage, ClientsPage, ClientPage, TransactionsPage } from "./pages/ClientPages";
import { MotifsPage, MotifPage, CommunitiesPage, CommunityPage } from "./pages/CatalogPages";
import { DisruptionPage, SensitivityPage } from "./pages/ExperimentPages";

type TransactionResponse = Wrapped<Transaction> & { daily: { date: string; direction: string; sum_kzt: number }[] };
type SensitivityResponse = Wrapped<Sensitivity> & { position_ranges: Record<string, { min: number; max: number }> };
const params = new URLSearchParams(location.search);
const validViews: View[] = ["overview", "graph", "clients", "client", "transactions", "motifs", "motif", "communities", "community", "disruption", "sensitivity", "assistant", "run"];
const savedTheme = (): "dark" | "light" => localStorage.getItem("money-graph-theme") === "light" ? "light" : "dark";

export function App() {
  const paramView = params.get("view") as View | null;
  const [view, setView] = useState<View>(paramView && validViews.includes(paramView) ? paramView : "overview");
  const [theme, setTheme] = useState<"dark" | "light">(savedTheme);
  const [selected, setSelected] = useState<string | undefined>(params.get("gid") ?? undefined);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [role, setRole] = useState(params.get("role") ?? "");
  const [cluster, setCluster] = useState(params.get("cluster") ?? "");
  const [depth, setDepth] = useState(params.get("depth") ?? "");
  const [minimum, setMinimum] = useState(params.get("min") ?? "0");
  const [includeSeed, setIncludeSeed] = useState(params.get("seed") !== "false");
  const [sort, setSort] = useState(params.get("sort") ?? "priority");
  const [offset, setOffset] = useState(Number(params.get("offset") ?? 0));
  const [hops, setHops] = useState(1);
  const [colorBy, setColorBy] = useState<"role" | "cluster">("role");
  const [graphTab, setGraphTab] = useState<"list" | "graph" | "card">("graph");
  const [chosenEdge, setChosenEdge] = useState<Edge | null>(null);
  const [motifGid, setMotifGid] = useState("");
  const [motifType, setMotifType] = useState("");
  const [motifOffset, setMotifOffset] = useState(0);
  const [chosenMotif, setChosenMotif] = useState<string>();
  const [clusterId, setClusterId] = useState<number>();
  const [clusterOffset, setClusterOffset] = useState(0);
  const graphViewport = useRef<GraphViewport | null>(null);
  const graphCentered = useRef<string | undefined>();

  const summary = useQuery({ queryKey: ["summary"], queryFn: () => getJson<Summary>("/api/summary") });
  const top = useQuery({ queryKey: ["top"], queryFn: () => getJson<Wrapped<Node>>("/api/top?limit=20") });
  const clusters = useQuery({ queryKey: ["clusters"], queryFn: () => getJson<Wrapped<Cluster>>("/api/clusters") });
  const listParams = useMemo(() => {
    const next = new URLSearchParams({ q: query, role, min_priority: minimum || "0", include_seed: String(includeSeed), offset: String(offset), limit: "50", sort });
    if (cluster) next.set("cluster_id", cluster);
    if (depth) next.set("depth", depth);
    return next;
  }, [query, role, minimum, includeSeed, offset, sort, cluster, depth]);
  const list = useQuery({ queryKey: ["nodes", listParams.toString()], enabled: view === "clients" || view === "graph", queryFn: () => getJson<Wrapped<Node>>(`/api/nodes?${listParams}`) });
  const node = useQuery({ queryKey: ["node", selected], enabled: !!selected && ["graph", "client", "transactions"].includes(view), queryFn: () => getJson<{ run_id: string; item: Node }>(`/api/nodes/${selected}`) });
  const network = useQuery({ queryKey: ["network", selected, hops], enabled: !!selected && view === "graph", queryFn: () => getJson<Neighborhood>(`/api/nodes/${selected}/neighborhood?hops=${hops}`) });
  const transactions = useQuery({ queryKey: ["transactions", selected], enabled: !!selected && view === "transactions", queryFn: () => getJson<TransactionResponse>(`/api/nodes/${selected}/transactions`) });
  const motifParams = useMemo(() => { const next = new URLSearchParams({ offset: String(motifOffset), limit: "30" }); if (motifGid) next.set("gid", motifGid); if (motifType) next.set("type", motifType); return next; }, [motifGid, motifType, motifOffset]);
  const motifList = useQuery({ queryKey: ["motifs", motifParams.toString()], enabled: view === "motifs", retry: false, queryFn: () => getJson<Wrapped<Motif>>(`/api/typologies?${motifParams}`) });
  const motif = useQuery({ queryKey: ["motif", chosenMotif], enabled: !!chosenMotif && view === "motif", queryFn: () => getJson<{ run_id: string; item: Motif }>(`/api/typologies/${chosenMotif}`), retry: false });
  const community = useQuery({ queryKey: ["community", clusterId], enabled: clusterId != null && view === "community", queryFn: () => getJson<{ run_id: string; item: Cluster }>(`/api/clusters/${clusterId}`) });
  const communityNodes = useQuery({ queryKey: ["community-nodes", clusterId, clusterOffset], enabled: clusterId != null && view === "community", queryFn: () => getJson<Wrapped<Node>>(`/api/nodes?cluster_id=${clusterId}&offset=${clusterOffset}&limit=50`) });
  const disruption = useQuery({ queryKey: ["disruption"], enabled: view === "disruption", queryFn: () => getJson<Wrapped<Disruption>>("/api/disruption") });
  const sensitivity = useQuery({ queryKey: ["sensitivity"], enabled: view === "sensitivity", queryFn: () => getJson<SensitivityResponse>("/api/sensitivity") });
  const aiStatus = useQuery({
    queryKey: ["ai-status"],
    enabled: view === "assistant",
    queryFn: () => getJson<{ available: boolean; message: string }>("/api/assistant/status"),
    retry: false,
    refetchInterval: view === "assistant" ? 5000 : false,
    refetchOnWindowFocus: "always",
  });

  useEffect(() => { if (!selected && top.data?.items[0]) setSelected(top.data.items[0].gid); }, [top.data, selected]);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("money-graph-theme", theme); }, [theme]);
  useEffect(() => { const next = new URLSearchParams({ view, q: query, role, cluster, depth, min: minimum, seed: String(includeSeed), offset: String(offset), sort }); if (selected) next.set("gid", selected); history.replaceState(null, "", `${location.pathname}?${next}`); }, [view, query, role, cluster, depth, minimum, includeSeed, offset, sort, selected]);

  const runId = summary.data?.run_id;
  const mismatch = Boolean(runId && [top.data?.run_id, clusters.data?.run_id, list.data?.run_id, node.data?.run_id, network.data?.run_id, transactions.data?.run_id, motifList.data?.run_id, motif.data?.run_id].some(id => id && id !== runId));
  const navigate = (next: View) => setView(next);
  const openClient = (gid: string) => { setSelected(gid); setChosenEdge(null); setView("client"); };
  const openGraph = (gid: string) => { setSelected(gid); setChosenEdge(null); setGraphTab("graph"); setView("graph"); };
  const openTransactions = (gid: string) => { setSelected(gid); setView("transactions"); };
  const openMotifs = (gid = "") => { setMotifGid(gid); setMotifOffset(0); setView("motifs"); };
  const openMotif = (id: string) => { setChosenMotif(id); setView("motif"); };
  const openCommunity = (id: number) => { setClusterId(id); setClusterOffset(0); setView("community"); };
  const changeFilter = (key: "query" | "role" | "cluster" | "depth" | "minimum" | "includeSeed" | "sort", value: string | boolean) => { setOffset(0); switch (key) { case "query": setQuery(String(value)); break; case "role": setRole(String(value)); break; case "cluster": setCluster(String(value)); break; case "depth": setDepth(String(value)); break; case "minimum": setMinimum(String(value)); break; case "includeSeed": setIncludeSeed(Boolean(value)); break; case "sort": setSort(String(value)); break; } };
  const resetFilters = () => { setQuery(""); setRole(""); setCluster(""); setDepth(""); setMinimum("0"); setIncludeSeed(true); setSort("priority"); setOffset(0); };
  const filterProps = { query, role, cluster, depth, minimum, includeSeed, sort, clusters: clusters.data?.items, onChange: changeFilter, onReset: resetFilters };

  return <Shell view={view} runId={runId} theme={theme} onTheme={() => setTheme(value => value === "dark" ? "light" : "dark")} onNavigate={navigate} onSearch={openClient}>
    {mismatch && <Status tone="warning" message="Появился другой run_id. Обновите данные открытого расчёта." action={<button onClick={() => location.reload()}>Обновить данные</button>}/>}
    {summary.isError && <Status tone="error" message="Не удалось получить сведения о расчёте." action={<button onClick={() => location.reload()}>Повторить</button>}/>}
    {view === "overview" && <OverviewPage summary={summary.data} top={top.data?.items} loading={top.isLoading} onClient={openClient} onGraph={openGraph} onNavigate={navigate}/>}
    {view === "graph" && <GraphPage filterProps={filterProps} list={list.data} listLoading={list.isLoading} offset={offset} onPage={setOffset} node={node.data?.item} selected={selected} network={network.data} networkError={network.isError} hops={hops} onHops={setHops} colorBy={colorBy} onColorBy={setColorBy} theme={theme} tab={graphTab} onTab={setGraphTab} chosenEdge={chosenEdge} onEdge={setChosenEdge} viewportRef={graphViewport} centeredRef={graphCentered} onSelect={setSelected} onClient={openClient} onTransactions={openTransactions}/>}
    {view === "clients" && <ClientsPage filterProps={filterProps} list={list.data} loading={list.isLoading} error={list.isError} selected={selected} offset={offset} onPage={setOffset} onClient={openClient} onGraph={openGraph}/>}
    {view === "client" && <ClientPage node={node.data?.item} loading={node.isLoading} error={node.isError} selected={selected} onClient={openClient} onGraph={openGraph} onTransactions={openTransactions} onMotifs={openMotifs} onMotif={openMotif}/>}
    {view === "transactions" && <TransactionsPage node={node.data?.item} data={transactions.data} loading={transactions.isLoading} error={transactions.isError} summary={summary.data} onGraph={openGraph} onClient={openClient} onMotifs={openMotifs}/>}
    {view === "motifs" && <MotifsPage list={motifList.data} loading={motifList.isLoading} error={motifList.isError} gid={motifGid} onGid={value => { setMotifGid(value); setMotifOffset(0); }} type={motifType} onType={value => { setMotifType(value); setMotifOffset(0); }} offset={motifOffset} onPage={setMotifOffset} onMotif={openMotif}/>}
    {view === "motif" && <MotifPage motif={motif.data?.item} loading={motif.isLoading} error={motif.isError} onClient={openClient} onGraph={openGraph}/>}
    {view === "communities" && <CommunitiesPage clusters={clusters.data?.items} loading={clusters.isLoading} onCommunity={openCommunity}/>}
    {view === "community" && <CommunityPage cluster={community.data?.item} loading={community.isLoading} error={community.isError} nodes={communityNodes.data} nodesLoading={communityNodes.isLoading} nodesError={communityNodes.isError} offset={clusterOffset} onPage={setClusterOffset} onClient={openClient} onGraph={openGraph}/>}
    {view === "disruption" && <DisruptionPage items={disruption.data?.items} loading={disruption.isLoading} onClient={openClient}/>}
    {view === "sensitivity" && <SensitivityPage items={sensitivity.data?.items} loading={sensitivity.isLoading} onClient={openClient}/>}
    {view === "assistant" && <AssistantPage available={aiStatus.isSuccess && aiStatus.data.available} loading={aiStatus.isPending} statusError={aiStatus.isError} message={aiStatus.data?.message} onRetryStatus={() => void aiStatus.refetch()} selectedGid={selected} runId={runId} onNavigate={navigate} onClient={openClient} onMotif={openMotif}/>}
    {view === "run" && <RunPage summary={summary.data}/>}
  </Shell>;
}
