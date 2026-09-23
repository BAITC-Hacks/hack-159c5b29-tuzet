import { useEffect, useRef, useState } from "react";
import { money, score, type AssistantResponse, type Node, type Summary } from "../api";
import { type View } from "../data/ui";
import { GidButton, MetricCard, Panel, RoleBadge, Status } from "../components/UI";

export interface OverviewPageProps { summary?: Summary; top?: Node[]; loading: boolean; onClient: (gid: string) => void; onGraph: (gid: string) => void; onNavigate: (view: View) => void }
export function OverviewPage({ summary, top, loading, onClient, onGraph, onNavigate }: Readonly<OverviewPageProps>) {
  return <><div className="mg-metric-grid"><MetricCard label="Клиентов" value={summary?.output.nodes?.toLocaleString("ru-RU") ?? "—"} note="Все gid сохранены"/><MetricCard label="Связей" value={summary?.output.edges?.toLocaleString("ru-RU") ?? "—"} note="Направленные рёбра"/><MetricCard label="Операций" value={summary?.output.transactions?.toLocaleString("ru-RU") ?? "—"} note="Внутрибанковские переводы"/><MetricCard label="Методика" value={summary?.methodology_version ?? "—"} note="Завершённый расчёт"/></div><Panel title="Границы наблюдения"><div className="mg-caveat-grid"><span>Даты операций точны до дня. Однодневный порядок неизвестен.</span><span>Входящий поток seed неполон.</span><span>После depth=4 дальнейшие переводы не наблюдаются.</span></div></Panel><Panel title="Первые клиенты для аналитической проверки" action={<button onClick={() => onNavigate("clients")}>Открыть реестр</button>}>{loading ? <Status message="Загружаем клиентов…"/> : <div className="mg-table-scroll"><table><thead><tr><th>gid</th><th>Роль</th><th className="mg-num">role_score</th><th className="mg-num">priority_score</th><th>Сообщество</th><th>Действие</th></tr></thead><tbody>{top?.slice(0, 5).map(item => <tr key={item.gid}><td><GidButton gid={item.gid} onClick={onClient}/></td><td><RoleBadge role={item.role}/></td><td className="mg-num">{score(item.role_score)}</td><td className="mg-num mg-strong">{score(item.priority_score)}</td><td>{item.cluster_id}</td><td><button className="mg-link" onClick={() => onGraph(item.gid)}>Граф</button></td></tr>)}</tbody></table></div>}</Panel><div className="mg-action-row"><button className="mg-primary" onClick={() => onNavigate("graph")}>Исследовать граф</button><button onClick={() => onNavigate("run")}>О расчёте и выгрузки</button></div></>;
}

export interface RunPageProps { summary?: Summary }
export function RunPage({ summary }: Readonly<RunPageProps>) {
  return <><div className="mg-metric-grid"><MetricCard label="run_id" value={<span className="mg-mono">{summary?.run_id ?? "—"}</span>} note="Завершённый расчёт"/><MetricCard label="Методика" value={summary?.methodology_version ?? "—"}/><MetricCard label="Клиенты / операции" value={`${summary?.output.nodes?.toLocaleString("ru-RU") ?? "—"} / ${summary?.output.transactions?.toLocaleString("ru-RU") ?? "—"}`}/><MetricCard label="Время расчёта" value={summary ? `${money.format(summary.elapsed_seconds)} сек` : "—"}/></div><div className="mg-two-cols"><Panel title="Период и конфигурация"><p>Период: {summary?.effective_config.period.start ?? "—"} → {summary?.effective_config.period.end ?? "—"}</p><p>Хеш конфигурации: <span className="mg-mono mg-wrap">{summary?.config_sha256 ?? "нет данных"}</span></p><details><summary>Эффективная конфигурация</summary><pre>{JSON.stringify(summary?.effective_config ?? {}, null, 2)}</pre></details></Panel><Panel title="Воспроизводимость"><p>Версия артефактов: {summary?.artifact_version ?? "нет данных"}</p><details><summary>Хеши входа и выхода</summary><pre>{JSON.stringify({ input: summary?.input, output_sha256: summary?.output_sha256 }, null, 2)}</pre></details><details><summary>Длительности фаз</summary><pre>{JSON.stringify(summary?.phase_seconds ?? {}, null, 2)}</pre></details></Panel></div><Panel title="CSV-выгрузки"><div className="mg-export-list"><a href="/api/exports/nodes_roles" download>nodes_roles.csv <span>gid · role · role_score · cluster_id · priority_score · evidence</span></a><a href="/api/exports/clusters" download>clusters.csv <span>cluster_id · n_nodes · n_seed · sum_kzt_internal</span></a><a href="/api/exports/top_nodes" download>top_nodes.csv <span>rank · gid · role · priority_score · why</span></a></div></Panel><Status tone="warning" message={summary?.warnings.join(" ") || "Даты точны до дня; граф ограничен наблюдаемой выборкой."}/></>;
}

export interface AssistantPageProps {
  available: boolean;
  message?: string;
  selectedGid?: string;
  runId?: string;
  onNavigate: (view: View) => void;
  onClient: (gid: string) => void;
  onMotif: (motifId: string) => void;
}
export function AssistantPage({ available, message, selectedGid, runId, onNavigate, onClient, onMotif }: Readonly<AssistantPageProps>) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AssistantResponse>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const currentRequest = useRef<AbortController | null>(null);
  useEffect(() => () => currentRequest.current?.abort(), []);
  async function ask() {
    currentRequest.current?.abort();
    const request = new AbortController();
    currentRequest.current = request;
    setBusy(true);
    setAnswer(undefined);
    setError("");
    try {
      const response = await fetch("/api/assistant/query", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, selected_gid: selectedGid ?? null, expected_run_id: runId ?? null }),
        signal: request.signal,
      });
      if (response.status === 409) throw new Error("Запуск изменился. Обновите страницу.");
      if (!response.ok) throw new Error("Не удалось обработать вопрос.");
      const data = await response.json() as AssistantResponse;
      if (data.run_id !== runId) throw new Error("Запуск изменился. Обновите страницу.");
      if (currentRequest.current === request) setAnswer(data);
    } catch (cause) {
      if (currentRequest.current === request && !request.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Ответ недоступен.");
      }
    } finally {
      if (currentRequest.current === request) {
        currentRequest.current = null;
        setBusy(false);
      }
    }
  }
  return <>
    <Panel title="Статус ассистента"><span className="mg-chip">{available ? "Настроен" : "AI отключён"}</span><p>{message ?? "Проверяем настройки…"}</p><p className="mg-help">Поиск, граф, карточки и выгрузки продолжают работать.</p></Panel>
    <Panel title="Задать вопрос">
      <p className="mg-help">Выбранный клиент: {selectedGid ?? "не выбран"}. Внешнему провайдеру передаются вопрос и выбранный gid; доказательства берутся из сохранённого расчёта.</p>
      <textarea aria-label="Вопрос ассистенту" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Почему у этого клиента такой приоритет?"/>
      <div className="mg-action-row"><button className="mg-primary" disabled={!available || !runId || question.trim().length < 3 || busy} onClick={ask}>{busy ? "Обрабатываем…" : "Спросить"}</button><button onClick={() => onNavigate("clients")}>Открыть поиск</button></div>
      <p className="mg-help">Примеры: «Почему у этого клиента такой приоритет?» · «Покажи циклы» · «Кто достижим от нескольких seed?»</p>
      {error && <Status tone="error" message={error} action={error.includes("Обновите") ? <button onClick={() => location.reload()}>Обновить</button> : undefined}/>}
    </Panel>
    {answer && <Panel title="Ответ ассистента"><p role="status">{answer.answer}</p>
      {answer.truncated && <Status tone="warning" message={`Показано ${answer.shown} из ${answer.total} результатов. Выдача неполная.`}/>}
      {answer.search_truncated && <Status tone="warning" message="Поиск мотивов в исходном расчёте был ограничен."/>}
      {answer.facts.length > 0 && <div className="mg-assistant-facts"><h3>Источники и ограничения</h3>{answer.facts.map(fact => <article key={fact.fact_id}>
        <button className="mg-link" onClick={() => fact.gid ? onClient(fact.gid) : onMotif(fact.fact_id)}>{fact.gid ? `Открыть клиента ${fact.gid}` : `Открыть мотив ${fact.fact_id}`}</button>
        {fact.temporal_status && <span> · {fact.temporal_status === "compatible" ? "Временно совместим" : "Только структура"}</span>}
        {fact.supporting_transaction_ids?.length ? <p>Внутренние ID операций: {fact.supporting_transaction_ids.join(", ")}</p> : null}
        {fact.rule && <p>Измерено: {Object.entries(fact.rule.measured).map(([key, value]) => `${key}=${value ?? "—"}`).join(", ")}; пороги: {Object.entries(fact.rule.thresholds).map(([key, value]) => `${key}=${value ?? "—"}`).join(", ")}</p>}
        {fact.paths?.map((path, index) => <p key={index}>Путь: {path.join(" → ")}</p>)}
        {fact.limitations?.map(item => <p className="mg-help" key={item}>{item}</p>)}
      </article>)}</div>}
    </Panel>}
  </>;
}
