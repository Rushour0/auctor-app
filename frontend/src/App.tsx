// Router shell: GitHub-operator login gate over the four top-level pages.
//
// BrowserRouter is provided by main.tsx, so this component is purely the route
// table. The structure is deliberately flat:
//
//   /login                     -> the standalone GitHub-OAuth screen (NOT a tab)
//   (RequireAuth)              -> session gate; unauthenticated -> /login
//     (AppShell)              -> persistent header + four-tab nav + <Outlet/>
//       index / conversations -> Conversations
//       crons                 -> Crons
//       posts                 -> Posts
//       metrics               -> Metrics
//   *                          -> bounce unknown paths back to the index
//
// There are EXACTLY four tabs — Login lives outside AppShell so it is a screen,
// not a fifth nav destination. This unit owns only the routing + gate wiring;
// AppShell and the four page components are authored by their own units.

import { Routes, Route, Navigate } from "react-router-dom";
import Login from "./auth/Login";
import RequireAuth from "./auth/RequireAuth";
import AppShell from "./components/AppShell";
import Conversations from "./pages/Conversations";
import Crons from "./pages/Crons";
import Posts from "./pages/Posts";
import Metrics from "./pages/Metrics";
import Onboarding from "./pages/Onboarding";
import ContentJob from "./pages/ContentJob";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Conversations />} />
          <Route path="conversations" element={<Conversations />} />
          <Route path="crons" element={<Crons />} />
          <Route path="posts" element={<Posts />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="content-job" element={<ContentJob />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
