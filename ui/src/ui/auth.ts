export const TOKEN_KEY = "furnisteel_admin_token";

/** Seconds before JWT `exp` to treat the session as expired (clock skew buffer). */
const EXPIRY_BUFFER_SEC = 30;

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function getTokenExpiryMs(token: string): number | null {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number" || !Number.isFinite(exp)) return null;
  return exp * 1000;
}

export function isTokenExpired(token: string, nowMs = Date.now()): boolean {
  const expMs = getTokenExpiryMs(token);
  if (expMs === null) return true;
  return nowMs >= expMs - EXPIRY_BUFFER_SEC * 1000;
}

export function loadStoredToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return null;
  if (isTokenExpired(token)) {
    localStorage.removeItem(TOKEN_KEY);
    return null;
  }
  return token;
}

export function saveToken(token: string): void {
  if (isTokenExpired(token)) {
    throw new Error("Received an already-expired token");
  }
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function msUntilExpiry(token: string): number | null {
  const expMs = getTokenExpiryMs(token);
  if (expMs === null) return null;
  return Math.max(0, expMs - EXPIRY_BUFFER_SEC * 1000 - Date.now());
}
