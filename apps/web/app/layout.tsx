import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "NEXUS AI — Mission Control",
  description: "Autonomous project orchestration, under your control.",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
