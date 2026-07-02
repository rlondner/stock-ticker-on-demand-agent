"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function SidebarNavLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: string;
  label: string;
}) {
  const pathname = usePathname();
  const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);
  const baseClasses =
    "flex items-center gap-4 px-4 py-2 rounded-lg font-semibold text-sm transition-all";
  const activeClasses =
    "text-af-on-surface bg-af-surface-container-low border-l-2 border-af-primary";
  const inactiveClasses =
    "text-af-on-surface-variant hover:bg-af-surface-container-low";
  return (
    <Link href={href} className={`${baseClasses} ${isActive ? activeClasses : inactiveClasses}`}>
      <span className="material-symbols-outlined">{icon}</span>
      <span>{label}</span>
    </Link>
  );
}
