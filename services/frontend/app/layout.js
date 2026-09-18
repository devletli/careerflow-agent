import "./globals.css";

export const metadata = {
  title: "AI Job Agent Dashboard",
  description: "Pipeline monitor, job review, application history and settings",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
