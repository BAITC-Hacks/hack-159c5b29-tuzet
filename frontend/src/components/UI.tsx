import type { ReactNode } from "react";
import { money, score, type Node } from "../api";
import { contributionLabels, roleLabels } from "../data/ui";

export interface PanelProps { title?: string; children: ReactNode; className?: string; action?: ReactNode }
export function Panel({ title, children, className = "", action }: Readonly<PanelProps>) {
  return <section className={`mg-panel ${className}`}><div className="mg-panel-heading">{title && <h2>{title}</h2>}{action}</div>{children}</section>;
}

export interface MetricCardProps { label: string; value: ReactNode; note?: string }
export function MetricCard({ label, value, note }: Readonly<MetricCardProps>) {
  return <div className="mg-metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

export interface RoleBadgeProps { role: string }
export function RoleBadge({ role }: Readonly<RoleBadgeProps>) {
  return <span className={`mg-role mg-role-${role}`}>{roleLabels[role] ?? role}</span>;
}

export interface GidButtonProps { gid: string; onClick: (gid: string) => void; label?: string }
export function GidButton({ gid, onClick, label }: Readonly<GidButtonProps>) {
  return <button className="mg-link mg-gid" onClick={() => onClick(gid)} title={gid}>{label ?? gid}</button>;
}

export interface StatusProps { message: string; tone?: "neutral" | "warning" | "error"; action?: ReactNode }
export function Status({ message, tone = "neutral", action }: Readonly<StatusProps>) {
  return <div className={`mg-status mg-status-${tone}`} role={tone === "error" ? "alert" : "status"}><span>{message}</span>{action}</div>;
}

export interface PagerProps { offset: number; pageSize: number; total: number; onPage: (offset: number) => void; label?: string }
export function Pager({ offset, pageSize, total, onPage, label }: Readonly<PagerProps>) {
  return <div className="mg-pager"><span>{label ?? `${total ? offset + 1 : 0}–${Math.min(total, offset + pageSize)} из ${total}`}</span><div><button disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - pageSize))} aria-label="Предыдущая страница">Назад</button><button disabled={offset + pageSize >= total} onClick={() => onPage(offset + pageSize)} aria-label="Следующая страница">Далее</button></div></div>;
}

export interface ClientHeaderProps { node: Node; onGraph: () => void; onTransactions: () => void; onMotifs: () => void }
export function ClientHeader({ node, onGraph, onTransactions, onMotifs }: Readonly<ClientHeaderProps>) {
  return <Panel title="Карточка клиента" className="mg-client-header"><div className="mg-client-id"><span className="mg-eyebrow">Клиент</span><strong className="mg-gid">{node.gid}</strong><button onClick={() => void navigator.clipboard?.writeText(node.gid)}>Копировать</button></div><div className="mg-chip-row"><RoleBadge role={node.role}/><span className="mg-chip">role_score {score(node.role_score)}</span><span className="mg-chip">priority {score(node.priority_score)}</span><span className="mg-chip">Сообщество {node.cluster_id}</span><span className="mg-chip">depth {node.depth}</span>{node.is_seed && <span className="mg-chip">seed</span>}</div><p className="mg-evidence">{node.evidence}</p><div className="mg-action-row"><button className="mg-primary" onClick={onGraph}>В графе</button><button onClick={onTransactions}>Операции</button><button onClick={onMotifs}>Мотивы</button></div></Panel>;
}

export interface PriorityBreakdownProps { contributions?: Record<string, number>; total?: number }
export function PriorityBreakdown({ contributions, total }: Readonly<PriorityBreakdownProps>) {
  const entries = Object.entries(contributions ?? {});
  return <Panel title="Почему такой приоритет"><div className="mg-bars">{entries.length ? entries.map(([key, value]) => <div className="mg-bar-row" key={key}><span>{contributionLabels[key] ?? key}</span><div className="mg-bar"><i style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}/></div><b>+{score(value)}</b></div>) : <span className="mg-muted">Не рассчитано</span>}</div><div className="mg-total"><strong>Итого priority</strong><b>{score(total)}</b></div><p className="mg-help">Пять вкладов объясняют приоритет проверки. Это не вероятность вины.</p></Panel>;
}

export interface RuleTableProps { rules?: NonNullable<Node["details"]>["rules"] }
export function RuleTable({ rules }: Readonly<RuleTableProps>) {
  return <Panel title="Почему назначена роль"><div className="mg-table-scroll"><table><thead><tr><th>Роль</th><th>Допуск</th><th>Выбрана</th><th>Измерено</th><th>Порог</th><th className="mg-num">score</th></tr></thead><tbody>{Object.entries(rules ?? {}).map(([name, rule]) => <tr key={name}><td><RoleBadge role={name}/></td><td>{rule.eligible ? "Да" : "Нет"}</td><td>{rule.selected ? "Да" : "Нет"}</td><td>{Object.entries(rule.measured).map(([key, value]) => `${key}: ${value == null ? "нет данных" : String(value)}`).join("; ")}</td><td>{Object.entries(rule.thresholds).map(([key, value]) => `${key}: ${value == null ? "не определён" : String(value)}`).join("; ")}</td><td className="mg-num">{score(rule.score)}</td></tr>)}</tbody></table></div>{!rules && <p className="mg-muted">Не рассчитано</p>}</Panel>;
}

export interface MoneyValueProps { value?: number | null }
export function MoneyValue({ value }: Readonly<MoneyValueProps>) { return <>{value == null ? "Нет данных" : `${money.format(value)} KZT`}</>; }
