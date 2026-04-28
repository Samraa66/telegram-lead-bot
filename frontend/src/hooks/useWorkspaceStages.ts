import { useEffect, useState } from "react";
import { fetchPipeline, PipelineConfig } from "../api/pipeline";

let cached: PipelineConfig | null = null;
const subscribers = new Set<(p: PipelineConfig) => void>();

export function refreshPipeline(): Promise<PipelineConfig> {
  return fetchPipeline().then((p) => {
    cached = p;
    subscribers.forEach((cb) => cb(p));
    return p;
  });
}

export function useWorkspaceStages(): PipelineConfig | null {
  const [config, setConfig] = useState<PipelineConfig | null>(cached);
  useEffect(() => {
    const cb = (p: PipelineConfig) => setConfig(p);
    subscribers.add(cb);
    if (!cached) refreshPipeline().catch(() => {});
    return () => { subscribers.delete(cb); };
  }, []);
  return config;
}
