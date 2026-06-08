import { api } from "./client";
import type {
  BootstrapTokenResponse,
  ListResponse,
  OrganizationInvite,
  OrganizationInviteCreateResponse,
  OrganizationInviteStatus,
  UserRole
} from "../types/api";

export interface CreateOrganizationInvitePayload {
  email: string;
  full_name?: string | null;
  role: UserRole;
  expires_in_days: number;
}

export interface AcceptOrganizationInvitePayload {
  token: string;
  full_name?: string | null;
  password: string;
}

export const organizationInvitesApi = {
  create: (payload: CreateOrganizationInvitePayload) =>
    api
      .post<OrganizationInviteCreateResponse>("/api/v1/organization-invites", payload)
      .then((response) => response.data),
  list: (params?: { status?: OrganizationInviteStatus; email?: string }) =>
    api
      .get<ListResponse<OrganizationInvite>>("/api/v1/organization-invites", { params })
      .then((response) => response.data),
  revoke: (inviteId: string) =>
    api
      .post<OrganizationInvite>(`/api/v1/organization-invites/${inviteId}/revoke`)
      .then((response) => response.data),
  accept: (payload: AcceptOrganizationInvitePayload) =>
    api
      .post<BootstrapTokenResponse>("/api/v1/organization-invites/accept", payload)
      .then((response) => response.data)
};
