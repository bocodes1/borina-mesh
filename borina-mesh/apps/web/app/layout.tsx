import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Toaster } from "@/components/ui/sonner";
import { CommandPalette } from "@/components/command-palette";
import { ToastListener } from "@/components/toast-listener";
import "./globals.css";

export const metadata: Metadata = {
  title: "Borina",
  description: "Multi-agent command center",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} font-sans antialiased`}>
        <div className="grid-bg min-h-screen">
          {children}
        </div>
        <CommandPalette />
        <ToastListener />
        <Toaster />
      </body>
    </html>
  );
}
