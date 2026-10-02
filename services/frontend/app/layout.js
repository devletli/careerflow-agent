import "./globals.css";

export const metadata = {
  title: "AI Job Agent Dashboard",
  description: "Pipeline monitor, job review, application history and settings",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("ai-job-agent-theme");if(!t){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme="light";}})();`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
