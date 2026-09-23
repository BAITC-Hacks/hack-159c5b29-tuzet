export type Node = {
  gid: string; role: string; role_score: number; cluster_id: number; priority_score: number;
  evidence: string; depth: number; is_seed: boolean; in_deg: number; out_deg: number;
  in_kzt: number; out_kzt: number; in_tx: number; out_tx: number; pagerank: number;
  betweenness: number; seed_reach: number; min_seed_distance: number | null;
  pass_through: number | null; temporal_ratio: number; temporal_matched_kzt: number; same_day_ambiguous_count: number;
  truncated_by_depth: boolean; incomplete_observation_window: boolean;
  details?: { role_scores: Record<string, number>; priority_contributions: Record<string, number>;
    seed_paths: string[][]; typologies: string[]; motif_ids: string[]; limitations: string[];
    hits: Record<string, number | string | boolean | null>; independent_seed_branches: { count: number; paths: string[][] } | null;
    rules: Record<string, { score: number; eligible: boolean; selected: boolean; measured: Record<string, number | boolean | null>; thresholds: Record<string, number | null>; threshold_status?: string }>;
    daily: { days: DailyFeature[] }; temporal_matches: Record<string, string | number>[] };
};
export type DailyFeature = { date: string; in_count: number; out_count: number; in_kzt: number; out_kzt: number; sender_count: number; receiver_count: number };
export type Summary = { run_id: string; output: { nodes: number; edges: number; transactions: number; clusters?: number; motifs?: number }; elapsed_seconds: number; methodology_version: string; artifact_version?: string; warnings: string[]; effective_config: { period: { start: string; end: string }; typologies: { temporal_max_days: number }; [key: string]: unknown }; config_sha256?: string; input?: Record<string, unknown>; output_sha256?: Record<string, string>; phase_seconds?: Record<string, number>; optional_status?: Record<string, unknown>; runtime?: Record<string, unknown> };
export type Edge = { source: string; target: string; sum_kzt: number; n_tx: number; depth: number };
export type Neighborhood = { run_id: string; nodes: Node[]; edges: Edge[]; truncated: boolean; available_nodes: number; shown_nodes: number; available_edges: number; shown_edges: number };
export type Motif = { motif_id: string; type: string; node_ids: string[]; edges: Edge[]; metrics: { compatible_tiyn: number; compatible_kzt: number; dates: string[]; confirmation_route: string[]; confirmations: { start_date: string; end_date: string; compatible_tiyn: number; transaction_ids: string[] }[] }; temporal_status: string; supporting_transaction_ids: string[]; limitations: string[] };
export type Cluster = { cluster_id: number; n_nodes: number; n_seed: number; sum_kzt_internal: number; top_gids: string[]; top_nodes?: Node[]; hypothesis: string };
export type Transaction = { transaction_id: string; src: string; dst: string; date: string; sum_kzt: number; direction: string; counterparty_gid: string };
export type Disruption = { kind: string; removed_gids: string[]; before: Record<string, number>; after: Record<string, number>; relative_seed_coverage_change: number | null };
export type Sensitivity = { group: string; factor: number; overlap_top20: number; entered_gids: string[]; left_gids: string[]; max_position_change: number };
export type Wrapped<T> = { run_id: string; items: T[]; total?: number; offset?: number; limit?: number };
export type AssistantFact = {
  fact_id: string; gid?: string; node_ids?: string[]; type?: string;
  role?: string; role_score?: number; priority_score?: number; seed_reach?: number;
  temporal_status?: string; supporting_transaction_ids?: string[];
  paths?: string[][]; limitations?: string[];
  rule?: { measured: Record<string, number | boolean | null>; thresholds: Record<string, number | null> };
};
export type AssistantResponse = {
  run_id: string; status: string; answer: string; facts: AssistantFact[];
  total: number; shown: number; truncated: boolean; search_truncated: boolean;
};
export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
export const money = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const score = (value: number | null | undefined) => value == null ? "—" : value.toFixed(3);
export const metric = (value: number | null | undefined) => value == null ? "—" : value !== 0 && Math.abs(value) < 0.001 ? value.toExponential(2) : value.toFixed(3);
