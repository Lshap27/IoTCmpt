export const deviceKeys = {
  all: (deviceId: string) => ["device", deviceId] as const,
  latest: (deviceId: string) => ["device", deviceId, "latest"] as const,
  history: (deviceId: string) => ["device", deviceId, "history"] as const,
  reportHistory: (deviceId: string) => ["device", deviceId, "report-history"] as const,
  events: (deviceId: string) => ["device", deviceId, "events"] as const,
  ledger: (deviceId: string) => ["device", deviceId, "ledger"] as const,
  notifications: (deviceId: string) => ["device", deviceId, "notifications"] as const,
  ai: (deviceId: string) => ["device", deviceId, "ai"] as const,
  aiRun: (deviceId: string, runId: string) => ["device", deviceId, "ai-runs", runId] as const,
  automationPolicy: (deviceId: string) => ["device", deviceId, "automation-policy"] as const,
  capabilities: (deviceId: string) => ["device", deviceId, "capabilities"] as const,
  pendingCommands: (deviceId: string) => ["device", deviceId, "pending-commands"] as const,
  commandStatuses: (deviceId: string) => ["device", deviceId, "command-statuses"] as const,
  processedEvents: (deviceId: string) => ["device", deviceId, "processed-events"] as const,
};

export const devicesKey = ["devices"] as const;
