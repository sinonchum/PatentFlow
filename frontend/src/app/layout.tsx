import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimPilot — Document Processing Workspace",
  description: "Enterprise-grade document processing for European Patent Attorneys. Local-first, secure, EPC compliant.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased font-sans">
        {children}
      </body>
    </html>
  );
}
