import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "双语文献阅读器",
  description: "本地多模型双语文献阅读工具"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
