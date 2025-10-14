// frontend/src/components/PrintTicketButton.jsx
import React from "react";

export default function PrintTicketButton({ bookingId, children = "Print ticket" }) {
  const handlePrint = () => {
    const url = `/api/sales/bookings/${bookingId}/ticket.pdf`;

    // скрытый iframe, дождаться загрузки и вызвать print()
    const iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.src = url;

    iframe.onload = () => {
      try {
        iframe.contentWindow?.focus();
        iframe.contentWindow?.print();
      } catch (e) {
        // запасной путь — открыть в новой вкладке
        const w = window.open(url, "_blank");
        if (!w) alert("Разрешите всплывающие окна для печати билета.");
      } finally {
        setTimeout(() => iframe.remove(), 1500);
      }
    };

    document.body.appendChild(iframe);
  };

  return (
    <button onClick={handlePrint}>
      {children}
    </button>
  );
}
