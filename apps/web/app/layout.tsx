import type { Metadata } from "next";
import { Shell } from "@/components/shell";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "ForgeFlow",
  description: "Agent-native version control and software delivery",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="font-sans">
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
