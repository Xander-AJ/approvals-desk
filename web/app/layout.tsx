import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { Providers } from "@/components/Providers";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "approvals-desk",
  description: "Human-in-the-loop approvals for agent-proposed money movements",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}` }} />
        <Providers>
          <div className="flex min-h-screen flex-col md:flex-row">
            <Nav />
            <main className="min-w-0 flex-1 space-y-4 px-4 py-6 md:px-8">
              <div className="mx-auto max-w-6xl space-y-4">{children}</div>
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
