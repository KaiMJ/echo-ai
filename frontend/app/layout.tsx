import type { Metadata } from "next";
import "@fontsource-variable/manrope";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://echo-agent.dev"),
  title: "Echo — A coding agent on your terms",
  description:
    "A small local coding agent for Linux. Work in your terminal, run your own models, and keep your code close.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Echo — A coding agent on your terms",
    description: "Your terminal. Your models. Your code.",
    url: "https://echo-agent.dev",
    type: "website",
    images: [
      {
        url: "/social.png",
        width: 1200,
        height: 630,
        alt: "Echo. Your code. Your machine. Your Echo.",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
