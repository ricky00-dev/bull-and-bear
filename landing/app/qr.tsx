"use client";

import { QRCodeSVG } from "qrcode.react";

export function AppQr({ url }: { url: string }) {
  return (
    <div className="rounded-2xl bg-white p-2">
      <QRCodeSVG value={url} size={72} bgColor="#ffffff" fgColor="#0b0c0e" />
    </div>
  );
}
