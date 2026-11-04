/** Minimal inline SVG icon set (stroke, currentColor). No emoji icons. */

import type { SVGProps } from "react";

function Svg({ children, ...props }: SVGProps<SVGSVGElement>): React.JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function GridIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </Svg>
  );
}

export function FileIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M6 2.5h8L19 8v13.5H6z" />
      <path d="M13.5 2.5V8H19" />
    </Svg>
  );
}

export function UploadIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 20h16" />
    </Svg>
  );
}

export function ShieldIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M12 2.5l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10v-6z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </Svg>
  );
}

export function ListIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <circle cx="4" cy="6" r="1" fill="currentColor" />
      <circle cx="4" cy="12" r="1" fill="currentColor" />
      <circle cx="4" cy="18" r="1" fill="currentColor" />
    </Svg>
  );
}

export function CpuIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="10" y="10" width="4" height="4" />
      <path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5" />
    </Svg>
  );
}

export function SlidersIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2.2" />
      <circle cx="8" cy="17" r="2.2" />
    </Svg>
  );
}

export function LogoutIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M14 4H5v16h9" />
      <path d="M10 12h11M18 8l4 4-4 4" />
    </Svg>
  );
}

export function AlertIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M12 3.5L22 20H2z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17.2" r="0.4" fill="currentColor" />
    </Svg>
  );
}

export function CheckCircleIcon(): React.JSX.Element {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.7 2.7L16.5 9" />
    </Svg>
  );
}

export function XCircleIcon(): React.JSX.Element {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </Svg>
  );
}

export function ClockIcon(): React.JSX.Element {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.5l3.5 2" />
    </Svg>
  );
}

export function ChevronRightIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M9 5l7 7-7 7" />
    </Svg>
  );
}

export function ChevronLeftIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M15 5l-7 7 7 7" />
    </Svg>
  );
}

export function CopyIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </Svg>
  );
}

export function RefreshIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M20 12a8 8 0 1 1-2.3-5.6" />
      <path d="M20 3.5V8h-4.5" />
    </Svg>
  );
}

export function ImageIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="9" cy="10" r="1.6" />
      <path d="M4.5 17.5l4.5-4.5 3 3 2.5-2.5 5 5" />
    </Svg>
  );
}

export function AudioIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M5 10v4M9.5 7v10M14 4.5v15M18.5 8.5V15.5" />
    </Svg>
  );
}

export function VideoIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="2.5" y="6" width="13" height="12" rx="2" />
      <path d="M15.5 10.5l6-3.5v10l-6-3.5" />
    </Svg>
  );
}

export function XIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  );
}

export function LockIcon(): React.JSX.Element {
  return (
    <Svg>
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7.5a4 4 0 0 1 8 0V11" />
    </Svg>
  );
}

export function EyeIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </Svg>
  );
}

export function EyeOffIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M4 4l16 16" />
      <path d="M9.9 5.9A9.5 9.5 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.7M6 7.5A16 16 0 0 1 2.5 12S6 18.5 12 18.5c1.1 0 2.2-.2 3.1-.6" />
    </Svg>
  );
}

export function MenuIcon(): React.JSX.Element {
  return (
    <Svg>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
  );
}

export function InfoIcon(): React.JSX.Element {
  return (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.8" r="0.4" fill="currentColor" />
    </Svg>
  );
}
