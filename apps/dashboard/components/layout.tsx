import { Bell, Search } from "lucide-react";
import { Sidebar } from "./sidebar";

export function AppLayout({ children }: { children: React.ReactNode }) {
  return <div className="app-shell"><Sidebar/><main className="main"><header className="topbar"><div className="search"><Search size={18}/><input aria-label="Search" placeholder="Search repositories, pull requests, and analyses"/></div><button className="icon-button" aria-label="Notifications"><Bell size={19}/><span className="notification-dot"/></button></header>{children}</main></div>;
}
