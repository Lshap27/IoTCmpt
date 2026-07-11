export const deviceKeys = {
  all: (deviceId: string) => ["device", deviceId] as const,
  latest: (deviceId: string) => ["device", deviceId, "latest"] as const,
  history: (deviceId: string) => ["device", deviceId, "history"] as const,
  reportHistory: (deviceId: string) => ["device", deviceId, "report-history"] as const,
  events: (deviceId: string) => ["device", deviceId, "events"] as const,
  ledger: (deviceId: string) => ["device", deviceId, "ledger"] as const,
  ai: (deviceId: string) => ["device", deviceId, "ai"] as const,
  pendingCommands: (deviceId: string) => ["device", deviceId, "pending-commands"] as const,
};

export const devicesKey = ["devices"] as const;
