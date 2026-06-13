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
export type ToolGovernanceStatus = "unreviewed" | "reviewed" | "governed";
export type GovernanceAlertType =
  | "new_tool_discovered"
  | "tool_removed"
  | "schema_changed"
  | "description_changed"
  | "high_risk_unreviewed"
  | "ungoverned_tool"
  | "policy_coverage_lost";
export type GovernanceAlertStatus = "open" | "acknowledged" | "resolved";
export type UserRole = "admin" | "auditor" | "operator" | "agent_owner";
export type MCPServerStatus = "connected" | "disconnected" | "error";
export type MCPTransportType = "streamable_http" | "sse";
export type MCPAuthType = "none" | "bearer" | "api_key";
export type MCPGatewayTokenStatus = "active" | "revoked";
export type OrganizationInviteStatus = "pending" | "accepted" | "expired" | "revoked";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  organization_membership: OrganizationMembership | null;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

export interface OrganizationMembership {
  id: string;
  organization_id: string;
  user_id: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  organization: Organization;
}

export interface OrganizationInvite {
  id: string;
  organization_id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  status: OrganizationInviteStatus;
  invited_by_user_id: string;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationInviteCreateResponse extends OrganizationInvite {
  token: string;
  invite_url: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface BootstrapTokenResponse extends TokenResponse {
  user: User;
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}

export interface AuditLog {
  id: string;
  organization_id: string | null;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
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
  discovered_from_mcp_server_id: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  schema_hash: string | null;
  schema_version: number | null;
  schema_last_updated_at: string | null;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
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
  total_mcp_servers: number;
  connected_mcp_servers: number;
  disconnected_mcp_servers: number;
  discovered_tools: number;
  governed_tools: number;
  unreviewed_tools: number;
  schema_changes_this_month: number;
  governance_health: number;
  open_governance_alerts: number;
  critical_governance_alerts: number;
  governance_gaps: number;
  policy_coverage_percentage: number;
  total_users: number;
  active_users: number;
  total_cost_usd: string;
  average_latency_ms: number;
}

export interface ToolGovernanceItem {
  id: string;
  agent_id: string;
  agent_name: string;
  mcp_server_id: string;
  mcp_server_name: string;
  name: string;
  description: string | null;
  governance_status: ToolGovernanceStatus;
  risk_level: RiskLevel;
  permission: ToolPermission;
  is_enabled: boolean;
  policy_count: number;
  policy_names: string[];
  governed_by: PolicyRuleEffect[];
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  schema_hash: string | null;
  schema_version: number | null;
  schema_last_updated_at: string | null;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  active_alerts_count: number;
  active_alert_ids: string[];
}

export interface ToolGovernanceSummary {
  total_tools: number;
  unreviewed_tools: number;
  reviewed_tools: number;
  governed_tools: number;
  high_risk_tools: number;
  schema_changes_this_month: number;
  risk_distribution: Record<string, number>;
  review_coverage: number;
  policy_coverage: number;
}

export interface GovernanceAlert {
  id: string;
  organization_id: string;
  alert_type: GovernanceAlertType;
  severity: RiskLevel;
  status: GovernanceAlertStatus;
  agent_id: string | null;
  tool_id: string | null;
  mcp_server_id: string | null;
  title: string;
  description: string;
  metadata: Record<string, unknown> | null;
  acknowledged_by_user_id: string | null;
  acknowledged_at: string | null;
  resolved_by_user_id: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GovernanceHealth {
  score: number;
  metrics: {
    unreviewed_tools: number;
    high_risk_unreviewed_tools: number;
    ungoverned_tools: number;
    unresolved_critical_alerts: number;
    unresolved_high_alerts: number;
  };
  open_alerts: number;
  critical_alerts: number;
  governance_gaps: number;
  explanation: string;
}

export interface PolicySimulation {
  affected_tools: { count: number; items: Array<{ id: string; name: string }> };
  affected_agents: { count: number; items: Array<{ id: string; name: string }> };
  affected_mcp_servers: { count: number; items: Array<{ id: string; name: string }> };
  current_coverage: {
    governed_tools: number;
    ungoverned_tools: number;
    policy_coverage_percentage: number;
  };
  projected_coverage: {
    governed_tools: number;
    ungoverned_tools: number;
    policy_coverage_percentage: number;
  };
  governance_gaps_resolved: number;
  governance_changes: {
    becoming_blocked: { count: number; tools: Array<{ id: string; name: string }> };
    becoming_approval_required: { count: number; tools: Array<{ id: string; name: string }> };
    becoming_explicitly_allowed: { count: number; tools: Array<{ id: string; name: string }> };
  };
  alert_impact: {
    potentially_resolved_ungoverned_tool: number;
    potentially_resolved_policy_coverage_lost: number;
    potentially_created_conflicts: number;
    potentially_created_overlaps: number;
  };
  warning_count: number;
  warnings: Array<{
    tool_id: string;
    tool_name: string;
    existing_policy_name: string;
    existing_effect: PolicyRuleEffect;
    proposed_effect: PolicyRuleEffect;
    conflicting_effects: boolean;
    reason: string;
  }>;
}

export interface PolicyImpactSummary {
  policy_coverage_percentage: number;
  governed_tools: number;
  ungoverned_tools: number;
  governance_gaps: number;
  conflict_count: number;
}

export interface MCPServer {
  id: string;
  agent_id: string | null;
  name: string;
  description: string | null;
  server_url: string;
  transport_type: MCPTransportType;
  auth_type: MCPAuthType;
  auth_secret_ref: string | null;
  request_timeout_seconds: number;
  connect_timeout_seconds: number;
  status: MCPServerStatus;
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface MCPServerSyncResponse {
  server_id: string;
  agent_id: string;
  discovered_tools_count: number;
  created_tools_count: number;
  updated_tools_count: number;
  status: MCPServerStatus;
  last_sync_at: string;
}

export interface MCPGatewayToken {
  id: string;
  agent_id: string;
  allowed_mcp_server_ids: string[];
  mcp_server_id: string | null;
  name: string;
  status: MCPGatewayTokenStatus;
  last_used_at: string | null;
  expires_at: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface MCPGatewayTokenCreated extends MCPGatewayToken {
  token: string;
}

export interface MCPGatewayTool {
  id: string;
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  risk_level: RiskLevel;
  permission: ToolPermission;
  governance_status: ToolGovernanceStatus;
}

export interface MCPGatewayCallResponse {
  execution_id: string;
  status: ExecutionStatus;
  policy_decision: PolicyRuleEffect;
  policy_decision_reason: string;
  approval_id: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  idempotent_replay: boolean;
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
