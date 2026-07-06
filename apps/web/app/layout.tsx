import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata = {
  // Keep in sync with the on-page <h1> (lib/ui-text.ts `title`) so the
  // browser tab / bookmark name matches what the user sees.
  title: "\u53f0\u7063\u6df9\u6c34\u98a8\u96aa\u958b\u653e\u5730\u5716",
  description: "\u6574\u5408\u516c\u958b\u8cc7\u6599\u8207\u6b77\u53f2\uff0f\u6f5b\u52e2\u5716\u8cc7\u7684\u53f0\u7063\u6df9\u6c34\u98a8\u96aa\u67e5\u8a62\u5730\u5716\u3002",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant-TW" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
