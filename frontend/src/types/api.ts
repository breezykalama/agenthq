export type RiskLevel = "low" | "medium" | "high" | "critical";
export type AgentStatus = "draft" | "active" | "disabled" | "archived";
export type ExecutionStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "blocked"
  | "requires_approval";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "cancelled";
export type IncidentStatus = "open" | "investigating" | "resolved" | "dismissed";
export type PolicyRuleScope = "global" | "agent" | "tool";
export type PolicyRuleEffect = "allow" | "require_approval" | "block";
export type ToolPermission = "read" | "write" | "execute" | "admin";

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  owner: string;
  department: string;
  risk_level: RiskLevel;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface AgentTool {
  id: string;
  agent_id: string;
  name: string;
  description: string | null;
  permission: ToolPermission;
  risk_level: RiskLevel;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface DashboardSummary {
  total_agents: number;
  active_agents: number;
  disabled_agents: number;
  archived_agents: number;
  total_executions: number;
  executions_today: number;
  succeeded_executions: number;
  failed_executions: number;
  blocked_executions: number;
  requires_approval_executions: number;
  pending_approvals: number;
  approved_approvals: number;
  rejected_approvals: number;
  open_incidents: number;
  investigating_incidents: number;
  resolved_incidents: number;
  critical_incidents: number;
  total_cost_usd: string;
  average_latency_ms: number;
}

export interface PolicyRule {
  id: string;
  name: string;
  description: string | null;
  scope: PolicyRuleScope;
  agent_id: string | null;
  tool_id: string | null;
  risk_level: RiskLevel;
  effect: PolicyRuleEffect;
  is_enabled: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface PolicyDecisionResponse {
  decision: PolicyRuleEffect;
  matched_rule_id: string | null;
  matched_rule_name: string | null;
  reason: string;
  requires_approval: boolean;
}

export interface Approval {
  id: string;
  agent_id: string;
  requested_action: string;
  requested_by: string;
  reason: string | null;
  status: ApprovalStatus;
  risk_level: RiskLevel;
  approver: string | null;
  decision_reason: string | null;
  requested_at: string;
  decided_at: string | null;
}

export interface Execution {
  id: string;
  agent_id: string;
  action_name: string;
  input_summary: string | null;
  output_summary: string | null;
  status: ExecutionStatus;
  risk_level: RiskLevel;
  tool_id: string | null;
  approval_id: string | null;
  policy_decision: PolicyRuleEffect | null;
  policy_decision_reason: string | null;
  policy_rule_id: string | null;
  cost_usd: string | null;
  latency_ms: number | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
}

export interface Incident {
  id: string;
  agent_id: string;
  execution_id: string | null;
  title: string;
  description: string;
  severity: RiskLevel;
  status: IncidentStatus;
  reported_by: string;
  assigned_to: string | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface ComplianceSummary {
  total_agents: number;
  total_executions: number;
  blocked_executions: number;
  executions_requiring_approval: number;
  approved_approvals: number;
  rejected_approvals: number;
  open_incidents: number;
  critical_incidents: number;
  policy_decisions_evaluated: number;
  audit_events: number;
}

export interface ComplianceIncident {
  id: string;
  agent_id: string;
  execution_id: string | null;
  title: string;
  severity: RiskLevel;
  status: IncidentStatus;
  reported_by: string;
  assigned_to: string | null;
  created_at: string;
  resolved_at: string | null;
}

export type CountMap = Record<string, number>;
