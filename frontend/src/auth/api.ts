// Frontend auth API helpers.
//
// Same-origin fetch wrappers around the backend GitHub-operator-login routes.
// The Vite dev proxy forwards /api to the FastAPI service on :8000, and the
// session cookie is httponly + same-origin, so `credentials: 'include'` is all
// that's needed to carry it. No external deps.

/** The logged-in GitHub operator, as returned by GET /api/auth/me. */
export type Operator = {
  login: string;
  gh_id: number;
};

/**
 * Fetch the current operator from the session cookie.
 * Returns the Operator on 200, or null when unauthenticated (401/other).
 */
export async function fetchMe(): Promise<Operator | null> {
  const r = await fetch('/api/auth/me', { credentials: 'include' });
  if (r.status === 200) return r.json();
  return null;
}

/** Kick off the GitHub OAuth authorize redirect. */
export function goToLogin(): void {
  window.location.href = '/api/auth/github/authorize';
}

/** Clear the server session and return to the login screen. */
export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/login';
}
