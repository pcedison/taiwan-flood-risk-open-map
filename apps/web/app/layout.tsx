import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata = {
  title: "\u53f0\u7063\u6df9\u6c34\u98a8\u96aa\u6aa2\u8996",
  description: "Map-first flood risk assessment interface for Taiwan.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant-TW">
      <body>{children}</body>
    </html>
  );
}
