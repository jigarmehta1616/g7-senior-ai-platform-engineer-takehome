import type {
  AuditEventList,
  CaseDetail,
  CaseList,
  Comment,
  CustomerSummary,
  EscalationReason,
  FaultMode,
  Persona,
  Problem,
  ReceivedWebhook,
  Upstream,
} from "../types/api";
import type {
  ApiResult,
  HttpMethod,
  MetaListener,
  RequestOptions,
  ResponseMeta,
  SignInResult,
} from "../types/client";

/** Error carrying an RFC 9457 problem body. Network failures use status 0. */
export class ApiError extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.title);
    this.name = "ApiError";
  }

  get status(): number {
    return this.problem.status;
  }
}

const MOCK_ADMIN = `${window.location.protocol}//${window.location.hostname}:8081`;

/** The API itself gives up on a slow upstream after ~5 s, so 15 s means the network/server is stuck. */
const API_TIMEOUT_MS = 15_000;
const MOCK_TIMEOUT_MS = 5_000;

function networkError(path: string): ApiError {
  return new ApiError({
    type: "about:blank",
    title: "Can't reach the server",
    status: 0,
    detail: `No response from ${path}. Check that the API is running.`,
    correlationId: "",
  });
}

/** Parse a body that should be JSON; tolerate empty bodies and HTML error pages from proxies. */
function parseBody(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function timeoutError(path: string, ms: number): ApiError {
  return new ApiError({
    type: "about:blank",
    title: "Request timed out",
    status: 0,
    detail: `${path} didn't answer within ${String(ms / 1000)} seconds. Try again.`,
    correlationId: "",
  });
}

/** fetch with a hard timeout; network failures and timeouts become ApiErrors with status 0. */
async function fetchOrThrow(url: string, init: RequestInit = {}, timeoutMs: number = API_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    throw controller.signal.aborted ? timeoutError(url, timeoutMs) : networkError(url);
  } finally {
    window.clearTimeout(timer);
  }
}

/** The only place in the console that talks HTTP. Components call these typed methods. */
export class PlatformClient {
  private token: string | null = null;
  private readonly listeners = new Set<MetaListener>();

  setToken(token: string | null): void {
    this.token = token;
  }

  onResponse(listener: MetaListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private async request<T>(method: HttpMethod, path: string, init: RequestOptions = {}): Promise<ApiResult<T>> {
    const headers: Record<string, string> = { ...init.headers };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (init.body !== undefined) headers["Content-Type"] = "application/json";

    const res = await fetchOrThrow(path, {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
    const correlationId = res.headers.get("x-correlation-id") ?? "";
    const meta: ResponseMeta = {
      method,
      path: path.split("?")[0] ?? path,
      status: res.status,
      correlationId,
      rateLimitRemaining: res.headers.get("ratelimit-remaining"),
    };
    this.listeners.forEach((listener) => {
      listener(meta);
    });

    const data = parseBody(await res.text());
    if (!res.ok && res.status !== 304) {
      const problem = (data && typeof data === "object" ? data : {}) as Partial<Problem>;
      throw new ApiError({
        title: res.statusText || "Request failed",
        type: "about:blank",
        correlationId,
        ...problem,
        status: res.status,
      });
    }
    if (data === null && res.status !== 304 && res.status !== 204) {
      throw new ApiError({
        title: "Unexpected response",
        detail: "The server returned a response the console couldn't read.",
        type: "about:blank",
        correlationId,
        status: res.status,
      });
    }
    return { data: data as T, headers: res.headers };
  }

  // ---- local dev IdP --------------------------------------------------------------
  async personas(): Promise<Persona[]> {
    const { data } = await this.request<{ personas: Persona[] }>("GET", "/dev/personas");
    return data.personas;
  }

  async signIn(persona: string): Promise<SignInResult> {
    const res = await fetchOrThrow("/dev/oauth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "urn:dev:grant-type:persona", persona }),
    });
    const body = parseBody(await res.text()) as { access_token?: string; scope?: string } | null;
    if (!res.ok || !body?.access_token) {
      throw new ApiError({
        title: "Sign-in failed",
        detail: `The local identity provider refused persona '${persona}'.`,
        type: "about:blank",
        correlationId: res.headers.get("x-correlation-id") ?? "",
        status: res.status,
      });
    }
    return { token: body.access_token, scopes: (body.scope ?? "").split(" ").filter(Boolean) };
  }

  // ---- platform API ---------------------------------------------------------------
  listCases(query: URLSearchParams): Promise<ApiResult<CaseList>> {
    return this.request("GET", `/v1/cases?${query.toString()}`);
  }

  getCase(id: string): Promise<ApiResult<CaseDetail>> {
    return this.request("GET", `/v1/cases/${encodeURIComponent(id)}`);
  }

  addComment(caseId: string, body: string, visibility: Comment["visibility"], idempotencyKey: string): Promise<ApiResult<Comment>> {
    return this.request("POST", `/v1/cases/${encodeURIComponent(caseId)}/comments`, {
      body: { body, visibility },
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }

  escalate(caseId: string, reason: EscalationReason, note: string, etag: string): Promise<ApiResult<CaseDetail>> {
    return this.request("POST", `/v1/cases/${encodeURIComponent(caseId)}/escalate`, {
      body: note ? { reason, note } : { reason },
      headers: { "If-Match": etag },
    });
  }

  getCustomer(id: string): Promise<ApiResult<CustomerSummary>> {
    return this.request("GET", `/v1/customers/${encodeURIComponent(id)}`);
  }

  auditEvents(limit = 100): Promise<ApiResult<AuditEventList>> {
    return this.request("GET", `/v1/audit-events?limit=${String(limit)}`);
  }

  // ---- mock upstream admin (resilience lab) ----------------------------------------
  private async mockJson<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetchOrThrow(`${MOCK_ADMIN}${path}`, init, MOCK_TIMEOUT_MS);
    const data = parseBody(await res.text());
    if (!res.ok || data === null) {
      throw new ApiError({
        title: "Mock upstreams error",
        detail: `${path} returned HTTP ${String(res.status)}.`,
        type: "about:blank",
        correlationId: "",
        status: res.status,
      });
    }
    return data as T;
  }

  async faults(): Promise<Record<Upstream, { mode: FaultMode }>> {
    return (await this.mockJson<{ faults: Record<Upstream, { mode: FaultMode }> }>("/_admin/faults")).faults;
  }

  async setFault(target: Upstream, mode: FaultMode): Promise<void> {
    await this.mockJson("/_admin/faults", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, mode, fail_next: mode === "flaky" ? 2 : 0 }),
    });
  }

  async receivedWebhooks(): Promise<ReceivedWebhook[]> {
    return (await this.mockJson<{ items: ReceivedWebhook[] }>("/_receiver/webhooks")).items;
  }
}

export const api = new PlatformClient();
