import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import "./accessibility.css";

const themeScript = `(() => {
  try {
    const saved = localStorage.getItem("marshrut-theme");
    const theme = saved === "dark" || saved === "light"
      ? saved
      : "light";
    document.documentElement.dataset.theme = theme;
  } catch (_) {
    document.documentElement.dataset.theme = "light";
  }
})();`;

export const metadata: Metadata = {
  title: "билайн бизнес · маршрут",
  description:
    "Планирование выездных работ, маршруты инженеров и изменения рабочего дня",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
