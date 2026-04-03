import { getToken, clearAuth } from "./auth";
import {
  MOCK_OVERVIEW, MOCK_CONVERSIONS, MOCK_STAGES, MOCK_HOURLY,
  MOCK_LEADS_OVER_TIME, MOCK_DAY_OF_WEEK, MOCK_CAMPAIGNS, MOCK_CAMPAIGN_FLAGS,
  MOCK_CREATIVES, MOCK_AD_ALERTS, MOCK_TRACKED_CAMPAIGNS,
} from "./mockData";

const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  : "";

async function apiFetch(path: string, init?: RequestInit) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
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

export type CampaignMetric = {
  campaign_id: string;
  campaign_name: string;
  spend: number;
  impressions: number;
  clicks: number;
  leads: number;
  deposits: number;
  cpl: number | null;   // cost per lead (EUR)
  cpd: number | null;   // cost per deposit (EUR)
};

export type CampaignFlag = {
  campaign_id: string;
  campaign_name: string;
  consecutive_days: number;
  latest_cpd: number;
};

export type CreativeMetric = {
  ad_id: string;
  ad_name: string;
  campaign_id: string;
  campaign_name: string;
  spend: number;
  impressions: number;
  clicks: number;
  leads: number;
  deposits: number;
  cpl: number | null;
  cpd: number | null;
};

export type AdAlert = {
  type: "spend" | "cpl" | "cpd";
  severity: "warning" | "critical";
  campaign_name: string;
  message: string;
  value: number;
  threshold: number;
};

export type TrackedCampaign = {
  id: number;
  source_tag: string;
  name: string;
  meta_campaign_id: string | null;
  link: string | null;
  leads: number;
  deposits: number;
  is_active: boolean;
  created_at: string;
};

function rangeParams(range: DateRange): string {
  if (!range) return "";
  return `?from_date=${range.from}&to_date=${range.to}`;
}

const MOCK = import.meta.env.VITE_USE_MOCK === "true";

export const fetchOverview = (range: DateRange): Promise<Overview> =>
  MOCK ? Promise.resolve(MOCK_OVERVIEW) : apiFetch(`/analytics/overview${rangeParams(range)}`);
export const fetchConversions = (range: DateRange): Promise<ConversionMetric[]> =>
  MOCK ? Promise.resolve(MOCK_CONVERSIONS) : apiFetch(`/analytics/conversions${rangeParams(range)}`);
export const fetchStageDistribution = (): Promise<StageCount[]> =>
  MOCK ? Promise.resolve(MOCK_STAGES) : apiFetch("/analytics/stage-distribution");
export const fetchHourlyHeatmap = (range: DateRange): Promise<HourCount[]> =>
  MOCK ? Promise.resolve(MOCK_HOURLY) : apiFetch(`/analytics/hourly-heatmap${rangeParams(range)}`);
export const fetchDayOfWeek = (range: DateRange): Promise<DayOfWeek[]> =>
  MOCK ? Promise.resolve(MOCK_DAY_OF_WEEK) : apiFetch(`/analytics/day-of-week${rangeParams(range)}`);
export const fetchLeadsOverTime = (range: DateRange): Promise<DayCount[]> => {
  if (MOCK) return Promise.resolve(MOCK_LEADS_OVER_TIME);
  const base = range ? rangeParams(range) : "?days=30";
  return apiFetch(`/analytics/leads-over-time${base}`);
};

export const fetchCampaigns = (range: DateRange): Promise<CampaignMetric[]> =>
  MOCK ? Promise.resolve(MOCK_CAMPAIGNS) : apiFetch(`/analytics/campaigns${rangeParams(range)}`);

export const fetchCampaignFlags = (): Promise<CampaignFlag[]> =>
  MOCK ? Promise.resolve(MOCK_CAMPAIGN_FLAGS) : apiFetch("/analytics/campaigns/flags");

export const fetchCreatives = (range: DateRange): Promise<CreativeMetric[]> =>
  MOCK ? Promise.resolve(MOCK_CREATIVES) : apiFetch(`/analytics/campaigns/creatives${rangeParams(range)}`);

export const fetchAdAlerts = (): Promise<AdAlert[]> =>
  MOCK ? Promise.resolve(MOCK_AD_ALERTS) : apiFetch("/analytics/alerts");

export const fetchTrackedCampaigns = (): Promise<TrackedCampaign[]> =>
  MOCK ? Promise.resolve(MOCK_TRACKED_CAMPAIGNS) : apiFetch("/campaigns");

export const createTrackedCampaign = (name: string, metaCampaignId?: string): Promise<TrackedCampaign> =>
  apiFetch("/campaigns", {
    method: "POST",
    body: JSON.stringify({ name, meta_campaign_id: metaCampaignId || null }),
  } as RequestInit);
