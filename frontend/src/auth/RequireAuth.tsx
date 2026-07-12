// Route gate for the four authenticated top-level pages.
//
// Wraps the AppShell + page routes as a react-router v6 layout element, so the
// GitHub OAuth callback's 302 to '/' lands inside the gate and passes straight
// through once the session cookie is set. On mount it resolves the current
// operator via GET /api/auth/me: while that's in flight it renders nothing,
// unauthenticated visitors are bounced to /login, and authenticated ones get
// the nested <Outlet />. No external deps beyond react-router.

import { useEffect, useState } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { fetchMe, type Operator } from './api';

type AuthState =
  | { status: 'pending' }
  | { status: 'in'; operator: Operator }
  | { status: 'out' };

/**
 * Gate the nested routes on a valid GitHub-operator session.
 *
 * - pending -> render a minimal loading placeholder
 * - out     -> redirect to /login (replace, so the gated URL isn't kept in history)
 * - in      -> render the matched child route via <Outlet />
 */
export default function RequireAuth() {
  const [state, setState] = useState<AuthState>({ status: 'pending' });

  useEffect(() => {
    let active = true;
    fetchMe().then((operator) => {
      if (!active) return;
      setState(operator ? { status: 'in', operator } : { status: 'out' });
    });
    return () => {
      active = false;
    };
  }, []);

  if (state.status === 'pending') return <div>Loading…</div>;
  if (state.status === 'out') return <Navigate to="/login" replace />;
  return <Outlet />;
}
