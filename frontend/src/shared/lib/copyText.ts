// Copies text to the clipboard. Never throws; resolves to whether a copy was made.
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* Fall through to the textarea method. */
  }
  let area: HTMLTextAreaElement | null = null;
  try {
    area = document.createElement("textarea");
    area.value = text;
    area.readOnly = true;
    area.setAttribute("aria-hidden", "true");
    area.style.cssText =
      "position:fixed;top:0;left:-9999px;opacity:0;pointer-events:none";
    document.body.appendChild(area);
    area.focus();
    area.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    try {
      area?.remove();
    } catch {
      /* Nothing to clean up. */
    }
  }
}
