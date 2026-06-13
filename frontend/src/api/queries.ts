import { api } from "./client";
import type {
  Agent,
  AgentTool,
  Approval,
  AuditLog,
  ComplianceIncident,
  ComplianceSummary,
  CountMap,
  DashboardSummary,
  Execution,
  Incident,
  GovernanceAlert,
  GovernanceHealth,
  ListResponse,
  MCPServer,
  MCPGatewayToken,
  PolicyDecisionResponse,
  PolicyImpactSummary,
  PolicyRule
  ,ToolGovernanceItem
  ,ToolGovernanceSummary,
  PolicySimulation
} from "../types/api";

export interface AuditLogFilters {
  action?: string;
  entity_type?: string;
  entity_id?: string;
  actor?: string;
  limit?: number;
  offset?: number;
}

export const endpoints = {
  dashboardSummary: () => api.get<DashboardSummary>("/api/v1/dashboard/summary").then((r) => r.data),
  agentsByRisk: () => api.get<CountMap>("/api/v1/dashboard/agents-by-risk").then((r) => r.data),
  executionsByStatus: () =>
    api.get<CountMap>("/api/v1/dashboard/executions-by-status").then((r) => r.data),
  approvalsByStatus: () =>
    api.get<CountMap>("/api/v1/dashboard/approvals-by-status").then((r) => r.data),
  agents: () => api.get<ListResponse<Agent>>("/api/v1/agents").then((r) => r.data),
  agent: (id: string) => api.get<Agent>(`/api/v1/agents/${id}`).then((r) => r.data),
  agentTools: (agentId: string) =>
    api.get<ListResponse<AgentTool>>(`/api/v1/agents/${agentId}/tools`).then((r) => r.data),
  policyRules: () =>
    api.get<ListResponse<PolicyRule>>("/api/v1/policy-rules").then((r) => r.data),
  approvals: () => api.get<ListResponse<Approval>>("/api/v1/approvals").then((r) => r.data),
  executions: () => api.get<ListResponse<Execution>>("/api/v1/executions").then((r) => r.data),
  incidents: () => api.get<ListResponse<Incident>>("/api/v1/incidents").then((r) => r.data),
  auditLogs: (params: AuditLogFilters) =>
    api.get<ListResponse<AuditLog>>("/api/v1/audit-logs", { params }).then((r) => r.data),
  mcpServers: () =>
    api.get<ListResponse<MCPServer>>("/api/v1/mcp-servers").then((r) => r.data),
  mcpGatewayTokens: (mcpServerId: string) =>
    api
      .get<ListResponse<MCPGatewayToken>>("/api/v1/mcp-gateway-tokens", {
        params: { mcp_server_id: mcpServerId }
      })
      .then((r) => r.data),
  complianceSummary: () =>
    api.get<ComplianceSummary>("/api/v1/compliance/summary").then((r) => r.data),
  complianceIncidents: () =>
    api.get<ListResponse<ComplianceIncident>>("/api/v1/compliance/incidents").then((r) => r.data),
  evaluatePolicy: (payload: unknown) =>
    api.post<PolicyDecisionResponse>("/api/v1/policy-decisions/evaluate", payload).then((r) => r.data),
  toolGovernance: () =>
    api.get<ListResponse<ToolGovernanceItem>>("/api/v1/tool-governance").then((r) => r.data),
  toolGovernanceSummary: () =>
    api.get<ToolGovernanceSummary>("/api/v1/tool-governance-summary").then((r) => r.data),
  governanceAlerts: (params: Record<string, string | number> = {}) =>
    api.get<ListResponse<GovernanceAlert>>("/api/v1/governance-alerts", { params }).then((r) => r.data),
  governanceHealth: () =>
    api.get<GovernanceHealth>("/api/v1/governance-health").then((r) => r.data),
  simulatePolicy: (payload: unknown) =>
    api.post<PolicySimulation>("/api/v1/policy-simulations", payload).then((r) => r.data),
  policyImpactSummary: () =>
    api.get<PolicyImpactSummary>("/api/v1/policy-impact-summary").then((r) => r.data)
};
