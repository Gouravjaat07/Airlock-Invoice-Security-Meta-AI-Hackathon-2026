/** Owner console shell: sidebar nav, mobile drawer, session footer. */

import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { useToast } from "../components/overlays";
import {
  CpuIcon,
  FileIcon,
  GridIcon,
  ListIcon,
  LogoutIcon,
  MenuIcon,
  ShieldIcon,
  SlidersIcon,
  UploadIcon,
  XIcon,
} from "../components/icons";
import { shortRef } from "../utils/format";

const NAV = [
  { to: "/", label: "Overview", icon: <GridIcon />, end: true },
  { to: "/cases", label: "Cases", icon: <FileIcon />, end: false },
  { to: "/cases/new", label: "New case", icon: <UploadIcon />, end: true },
  { to: "/proposals", label: "Proposals", icon: <ShieldIcon />, end: false },
  { to: "/audit", label: "Audit history", icon: <ListIcon />, end: true },
  { to: "/providers", label: "Providers", icon: <CpuIcon />, end: true },
  { to: "/settings", label: "Settings", icon: <SlidersIcon />, end: true },
];

function Brand(): React.JSX.Element {
  return (
    <Link to="/" className="ak-brand" aria-label="Airlock home">
      <span className="ak-brand-mark" aria-hidden="true">
        <ShieldIcon />
      </span>
      Airlock
    </Link>
  );
}

function SessionFooter({ onNavigate }: { onNavigate?: () => void }): React.JSX.Element {
  const { sessionId, expiresAt, logout } = useSession();
  const navigate = useNavigate();
  const { notify } = useToast();
  const [leaving, setLeaving] = useState(false);

  const onLogout = async (): Promise<void> => {
    setLeaving(true);
    try {
      await logout();
      onNavigate?.();
      navigate("/login", { replace: true });
    } finally {
      setLeaving(false);
    }
  };

  return (
    <div className="ak-side-foot">
      <span className="ak-session-line">
        Owner session {shortRef(sessionId)}
        {expiresAt ? ` · expires ${new Date(expiresAt).toLocaleTimeString()}` : ""}
      </span>
      <button
        type="button"
        className="ak-btn ak-btn--secondary ak-btn--sm"
        disabled={leaving}
        onClick={() => {
          void onLogout().catch(() => notify("Logout failed. The session may still be active.", "danger"));
        }}
      >
        <LogoutIcon /> Log out
      </button>
    </div>
  );
}

export function Shell(): React.JSX.Element {
  const [drawer, setDrawer] = useState(false);

  return (
    <div className="ak-shell">
      <aside className="ak-side" aria-label="Primary">
        <Brand />
        <nav className="ak-nav" aria-label="Sections">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "ak-active" : "")}
            >
              {item.icon} {item.label}
            </NavLink>
          ))}
        </nav>
        <SessionFooter />
      </aside>

      <div className="ak-topbar">
        <button type="button" className="ak-iconbtn" onClick={() => setDrawer(true)} aria-label="Open navigation">
          <MenuIcon />
        </button>
        <Brand />
      </div>

      {drawer ? (
        <div className="ak-drawer-backdrop" onMouseDown={() => setDrawer(false)}>
          <div className="ak-drawer" role="dialog" aria-modal="true" aria-label="Navigation">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <Brand />
              <button type="button" className="ak-iconbtn" onClick={() => setDrawer(false)} aria-label="Close navigation">
                <XIcon />
              </button>
            </div>
            <nav className="ak-nav" aria-label="Sections" style={{ marginTop: 12 }}>
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={() => setDrawer(false)}
                  className={({ isActive }) => (isActive ? "ak-active" : "")}
                >
                  {item.icon} {item.label}
                </NavLink>
              ))}
            </nav>
            <SessionFooter onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      ) : null}

      <main className="ak-main">
        <div className="ak-main-inner">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
