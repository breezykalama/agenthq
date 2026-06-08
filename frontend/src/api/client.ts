import axios from "axios";

export const AUTH_TOKEN_KEY = "agenthq_access_token";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  headers: {
    "Content-Type": "application/json"
  }
});

export function getStoredToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

api.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      clearStoredToken();
      window.dispatchEvent(new Event("agenthq:unauthorized"));
    }
    return Promise.reject(error);
  }
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return "AgentHQ is unavailable. Check your connection and try again.";
    if (error.response.status === 401) return "Your session has expired. Please sign in again.";
    if (error.response.status === 403) return "You do not have permission to access this resource.";
    if (error.response.status === 422) {
      const detail = error.response.data?.detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) => (typeof item?.msg === "string" ? item.msg : null))
          .filter(Boolean);
        return messages.length > 0
          ? `Please check the submitted values: ${messages.join("; ")}`
          : "Please check the submitted values and try again.";
      }
      return "Please check the submitted values and try again.";
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return "AgentHQ could not complete the request. Please try again.";
  }
  return "AgentHQ could not complete the request. Please try again.";
}
