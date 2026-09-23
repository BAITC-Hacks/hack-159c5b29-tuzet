export const roleLabels: Record<string, string> = {
  consolidator: "Сборщик",
  distributor: "Распределитель",
  transit: "Транзит",
  coordinator: "Связующий",
  terminal: "Наблюдаемый конец",
  peripheral: "Периферия",
};

export const contributionLabels: Record<string, string> = {
  structural: "Структура",
  seed_exposure: "Связь с seed",
  flow: "Оборот",
  typology: "Мотивы",
  temporal: "Время",
};

export const motifLabels: Record<string, string> = {
  fan_in: "Схождение",
  fan_out: "Разветвление",
  multi_seed_convergence: "Схождение seed",
  pass_through_chain: "Транзитная цепочка",
  cycle: "Цикл",
  scatter_gather: "Разделение и сбор",
  repeated_route: "Повторяемый маршрут",
};

export const roleOptions = ["", ...Object.keys(roleLabels)];
export const motifOptions = ["", ...Object.keys(motifLabels)];

export type View = "overview" | "graph" | "clients" | "client" | "transactions" | "motifs" | "motif" | "communities" | "community" | "disruption" | "sensitivity" | "assistant" | "run";

export const navigation: { view: View; label: string; icon: string }[] = [
  { view: "overview", label: "Обзор", icon: "▦" },
  { view: "graph", label: "Граф", icon: "◎" },
  { view: "clients", label: "Клиенты", icon: "☷" },
  { view: "motifs", label: "Мотивы", icon: "◇" },
  { view: "communities", label: "Сообщества", icon: "◌" },
  { view: "disruption", label: "Устойчивость", icon: "⌁" },
  { view: "sensitivity", label: "Чувствительность", icon: "≋" },
  { view: "assistant", label: "AI-ассистент", icon: "✦" },
];

export const viewTitles: Record<View, string> = {
  overview: "Обзор", graph: "Исследование графа", clients: "Реестр клиентов",
  client: "Полная карточка клиента", transactions: "Операции клиента", motifs: "Каталог мотивов",
  motif: "Детали мотива", communities: "Сообщества", community: "Детали сообщества",
  disruption: "Структурная устойчивость", sensitivity: "Чувствительность рейтинга",
  assistant: "AI-ассистент", run: "О расчёте и выгрузки",
};

export const analyticalCaveat = "Результаты — гипотезы для аналитической проверки, а не выводы о виновности.";
