import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Jarvis",
  description: "Your personal med school dashboard",
};

// Without this, mobile browsers render at desktop scale (980px virtual
// viewport) and require pinch-zoom. Next.js does NOT inject a viewport
// tag automatically — the export is the canonical way.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Keep the dark canvas matching --surface-0 so the iOS status bar /
  // Safari address bar tint don't flash white during navigation.
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#1c1c1e" },
    { media: "(prefers-color-scheme: light)", color: "#f5f5f7" },
  ],
};

// Pre-hydration script — picks the saved theme from localStorage and
// applies the matching class+data-attribute to <html> BEFORE any styles
// load. Prevents the "flash of dark" when the user has light theme saved
// (was hardcoded to `dark` on every SSR render → flicker on hydration).
const themeBootstrap = `
(function() {
  try {
    var saved = localStorage.getItem("jarvis-theme-v1");
    var theme = saved === "light" || saved === "dark" ? saved : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    if (theme === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.classList.add("dark");
  }
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // Default to dark for SSR (overwritten in <head> by the bootstrap
      // script before paint, see above). The class+attribute pair is
      // intentional: Tailwind's `dark:` variant keys off the class,
      // while our --foreground / --surface CSS vars switch on the
      // [data-theme="light"] attribute.
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className="min-h-full flex flex-col">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
