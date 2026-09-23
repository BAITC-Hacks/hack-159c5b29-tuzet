import type { Cluster, Node } from "../api";
import { score } from "../api";
import { roleLabels, roleOptions } from "../data/ui";
import { GidButton, Pager, RoleBadge, Status } from "./UI";

export interface ClientFiltersProps {
  query: string; role: string; cluster: string; depth: string; minimum: string; includeSeed: boolean; sort: string;
  clusters?: Cluster[];
  onChange: (key: "query" | "role" | "cluster" | "depth" | "minimum" | "includeSeed" | "sort", value: string | boolean) => void;
  onReset: () => void;
}
export function ClientFilters({ query, role, cluster, depth, minimum, includeSeed, sort, clusters, onChange, onReset }: Readonly<ClientFiltersProps>) {
  return <div className="mg-filters"><input aria-label="Поиск клиентов по gid" inputMode="numeric" placeholder="Поиск по gid" value={query} onChange={event => onChange("query", event.target.value)}/><select aria-label="Роль" value={role} onChange={event => onChange("role", event.target.value)}>{roleOptions.map(value => <option value={value} key={value}>{value ? roleLabels[value] : "Все роли"}</option>)}</select><select aria-label="Сообщество" value={cluster} onChange={event => onChange("cluster", event.target.value)}><option value="">Все сообщества</option>{clusters?.map(item => <option value={item.cluster_id} key={item.cluster_id}>Сообщество {item.cluster_id}</option>)}</select><select aria-label="Глубина" value={depth} onChange={event => onChange("depth", event.target.value)}><option value="">Все глубины</option>{[0,1,2,3,4].map(value => <option value={value} key={value}>depth {value}</option>)}</select><input aria-label="Минимальный priority" type="number" min="0" max="1" step="0.05" value={minimum} onChange={event => onChange("minimum", event.target.value)}/><label className="mg-check"><input type="checkbox" checked={includeSeed} onChange={event => onChange("includeSeed", event.target.checked)}/> Показывать seed</label><select aria-label="Сортировка" value={sort} onChange={event => onChange("sort", event.target.value)}><option value="priority">По priority</option><option value="gid">По gid</option><option value="role">По роли</option></select><button onClick={onReset}>Сбросить</button></div>;
}

export interface ClientTableProps { items?: Node[]; total: number; offset: number; loading: boolean; error: boolean; selected?: string; onSelect: (gid: string) => void; onGraph?: (gid: string) => void; onPage: (offset: number) => void }
export function ClientTable({ items, total, offset, loading, error, selected, onSelect, onGraph, onPage }: Readonly<ClientTableProps>) {
  if (loading) return <Status message="Загружаем реестр клиентов…"/>;
  if (error) return <Status tone="error" message="Не удалось загрузить реестр. Повторите запрос." action={<button onClick={() => location.reload()}>Повторить</button>}/>;
  if (!items?.length) return <Status message="По текущим фильтрам клиентов не найдено."/>;
  return <><div className="mg-table-scroll"><table><thead><tr><th>gid</th><th>Роль</th><th className="mg-num">role_score</th><th className="mg-num">priority_score</th><th>Сообщество</th><th>depth</th><th>seed</th><th>Действие</th></tr></thead><tbody>{items.map(item => <tr key={item.gid} className={item.gid === selected ? "selected" : ""}><td><GidButton gid={item.gid} onClick={onSelect}/></td><td><RoleBadge role={item.role}/></td><td className="mg-num">{score(item.role_score)}</td><td className="mg-num mg-strong">{score(item.priority_score)}</td><td>{item.cluster_id}</td><td>{item.depth}</td><td>{item.is_seed ? "Да" : "Нет"}</td><td><button className="mg-link" onClick={() => onGraph ? onGraph(item.gid) : onSelect(item.gid)}>{onGraph ? "Граф" : "Карточка"}</button></td></tr>)}</tbody></table></div><Pager offset={offset} pageSize={50} total={total} onPage={onPage}/></>;
}
