import { getToken, clearAuth } from "./auth";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

async function apiFetch(path: string) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (res.status === 401) {
    clearAuth();
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  return res.json();
}

export type Overview = {
  total_leads: number;
  new_today: number;
  new_this_week: number;
  total_deposited: number;
  overall_conversion: number;
  avg_days_to_deposit: number | null;
};

export type ConversionMetric = {
  label: string;
  from_entries: number;
  to_entries: number;
  rate: number | null;
  target: number;
};

export type StageCount = {
  stage: number;
  label: string;
  count: number;
};

export type HourCount = {
  hour: number;
  count: number;
};

export type DayCount = {
  date: string;
  count: number;
};

export type DayOfWeek = {
  day: string;
  leads: number;
  deposits: number;
};

export type DateRange = { from: string; to: string } | null;

function rangeParams(range: DateRange): string {
  if (!range) return "";
  return `?from_date=${range.from}&to_date=${range.to}`;
}

export const fetchOverview = (range: DateRange): Promise<Overview> =>
  apiFetch(`/analytics/overview${rangeParams(range)}`);
export const fetchConversions = (range: DateRange): Promise<ConversionMetric[]> =>
  apiFetch(`/analytics/conversions${rangeParams(range)}`);
export const fetchStageDistribution = (): Promise<StageCount[]> =>
  apiFetch("/analytics/stage-distribution");
export const fetchHourlyHeatmap = (range: DateRange): Promise<HourCount[]> =>
  apiFetch(`/analytics/hourly-heatmap${rangeParams(range)}`);
export const fetchDayOfWeek = (range: DateRange): Promise<DayOfWeek[]> =>
  apiFetch(`/analytics/day-of-week${rangeParams(range)}`);
export const fetchLeadsOverTime = (range: DateRange): Promise<DayCount[]> => {
  const base = range ? rangeParams(range) : "?days=30";
  return apiFetch(`/analytics/leads-over-time${base}`);
};
