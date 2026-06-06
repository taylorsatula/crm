class ApiError extends Error {
  constructor(payload, status) {
    const error = payload && payload.error ? payload.error : {};
    super(error.message || "API request failed");
    this.name = "ApiError";
    this.status = status;
    this.code = error.code || "API_ERROR";
    this.requestId = payload && payload.meta ? payload.meta.request_id : null;
    this.payload = payload;
  }
}

function cleanParams(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, value);
    }
  });
  return search;
}

async function request(path, options) {
  const opts = options || {};
  const headers = new Headers(opts.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (opts.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...opts,
    headers,
    credentials: "same-origin",
  });

  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    throw new ApiError({
      success: false,
      data: null,
      error: {
        code: "BAD_RESPONSE",
        message: "Response was not JSON",
      },
      meta: null,
    }, response.status);
  }

  if (!payload || typeof payload.success !== "boolean") {
    throw new ApiError({
      success: false,
      data: null,
      error: {
        code: "BAD_RESPONSE",
        message: "Response envelope was invalid",
      },
      meta: payload && payload.meta ? payload.meta : null,
    }, response.status);
  }

  if (!response.ok || !payload.success) {
    throw new ApiError(payload, response.status);
  }

  return payload.data;
}

function data(type, params, options) {
  const search = cleanParams({ type, ...(params || {}) });
  return request(`/api/data?${search.toString()}`, {
    method: "GET",
    signal: options && options.signal,
  });
}

function action(domain, actionName, body, options) {
  return request("/api/actions", {
    method: "POST",
    body: JSON.stringify({
      domain,
      action: actionName,
      data: body || {},
    }),
    signal: options && options.signal,
  });
}

const api = {
  ApiError,
  request,
  data,
  action,
  auth: {
    me(options) {
      return request("/auth/me", {
        method: "GET",
        signal: options && options.signal,
      });
    },
    requestLink(email, options) {
      return request("/auth/request-link", {
        method: "POST",
        body: JSON.stringify({ email }),
        signal: options && options.signal,
      });
    },
    logout(options) {
      return request("/auth/logout", {
        method: "POST",
        signal: options && options.signal,
      });
    },
    devAutobypass(options) {
      return request("/auth/dev-autobypass", {
        method: "POST",
        signal: options && options.signal,
      });
    },
  },
  tickets: {
    current(options) {
      return request("/api/data/tickets/current", {
        method: "GET",
        signal: options && options.signal,
      });
    },
    today(options) {
      return request("/api/data/tickets/today", {
        method: "GET",
        signal: options && options.signal,
      });
    },
  },
  control: {
    today(options) {
      return request("/api/data/today", {
        method: "GET",
        signal: options && options.signal,
      });
    },
    ticketPacket(ticketId, options) {
      return request(`/api/data/tickets/${encodeURIComponent(ticketId)}/packet`, {
        method: "GET",
        signal: options && options.signal,
      });
    },
    customerDossier(customerId, options) {
      return request(`/api/data/customers/${encodeURIComponent(customerId)}/dossier`, {
        method: "GET",
        signal: options && options.signal,
      });
    },
  },
  health: {
    ready(options) {
      return request("/health/ready", {
        method: "GET",
        signal: options && options.signal,
      });
    },
    live(options) {
      return request("/health/live", {
        method: "GET",
        signal: options && options.signal,
      });
    },
  },
};

window.api = api;

export { api, ApiError };
