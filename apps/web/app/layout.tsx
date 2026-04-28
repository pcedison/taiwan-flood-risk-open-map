import "./globals.css";

export const metadata = {
  title: "Flood Risk",
  description: "Map-first flood risk assessment interface.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

