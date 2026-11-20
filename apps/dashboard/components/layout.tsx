import { Search } from "lucide-react";
import { NotificationsMenu } from "./notifications-menu";
import { Sidebar } from "./sidebar";

export function AppLayout({ children }: { children: React.ReactNode }) {
  return <div className="app-shell"><Sidebar/><main className="main"><header className="topbar"><form className="search" action="/search" method="get" role="search"><Search size={18}/><input aria-label="Search" name="q" type="search" placeholder="Search repositories, pull requests, and analyses"/></form><NotificationsMenu/></header>{children}</main></div>;
}
