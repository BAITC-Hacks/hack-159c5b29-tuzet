import { useState, type ReactNode } from "react";
import { analyticalCaveat, navigation, viewTitles, type View } from "../data/ui";

export interface ShellProps {
  view: View;
  runId?: string;
  theme: "dark" | "light";
  onTheme: () => void;
  onNavigate: (view: View) => void;
  onSearch: (gid: string) => void;
  children: ReactNode;
}

export function Shell({ view, runId, theme, onTheme, onNavigate, onSearch, children }: Readonly<ShellProps>) {
  const [search, setSearch] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const navigate = (next: View) => { onNavigate(next); setMoreOpen(false); window.scrollTo(0, 0); };
  return <div className="mg-shell" data-theme={theme}>
    <aside className="mg-sidebar"><button className="mg-brand" onClick={() => navigate("overview")}><span className="mg-brand-mark">◎</span><span>Tuzet</span></button><p className="mg-sidebar-caption">Аналитическая платформа<br/><span className="mg-mono">{runId ?? "Загрузка расчёта…"}</span></p><nav aria-label="Разделы">{navigation.map(item => <button key={item.view} className={view === item.view ? "active" : ""} onClick={() => navigate(item.view)}><span>{item.icon}</span>{item.label}</button>)}</nav><button className={`mg-nav-bottom ${view === "run" ? "active" : ""}`} onClick={() => navigate("run")}>▤ <span>О расчёте и выгрузки</span></button></aside>
    <div className="mg-main"><header className="mg-topbar"><button className="mg-mobile-brand" onClick={() => navigate("overview")}>Tuzet</button><strong>{viewTitles[view]}</strong><span className="mg-run-chip mg-mono">{runId ?? "—"}</span><form onSubmit={event => { event.preventDefault(); if (search.trim()) onSearch(search.trim()); }}><input aria-label="Поиск по gid" inputMode="numeric" placeholder="Поиск по gid" value={search} onChange={event => setSearch(event.target.value)}/></form><button className="mg-theme" onClick={onTheme} aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</button></header>
      <main className="mg-content"><div className="mg-page-head"><div><p className="mg-eyebrow">Tuzet / завершённый расчёт</p><h1>{viewTitles[view]}</h1><p>{analyticalCaveat}</p></div></div>{children}</main><footer className="mg-footer mg-mono">run_id: {runId ?? "—"} · Результаты относятся к одному завершённому расчёту</footer></div>
    <nav className="mg-bottom-nav" aria-label="Мобильная навигация">{navigation.slice(0, 3).map(item => <button key={item.view} className={view === item.view ? "active" : ""} onClick={() => navigate(item.view)}><span>{item.icon}</span>{item.label}</button>)}<button className={moreOpen || !["overview", "graph", "clients"].includes(view) ? "active" : ""} onClick={() => setMoreOpen(value => !value)}><span>⋯</span>Ещё</button></nav>
    {moreOpen && <div className="mg-more-menu"><div className="mg-more-head"><strong>Разделы</strong><button onClick={() => setMoreOpen(false)} aria-label="Закрыть меню">×</button></div>{[...navigation.slice(3), { view: "run" as View, label: "О расчёте и выгрузки", icon: "▤" }].map(item => <button key={item.view} onClick={() => navigate(item.view)}><span>{item.icon}</span>{item.label}</button>)}<button onClick={onTheme}>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</button></div>}
  </div>;
}
