import type { components } from "../../../shared/api/schema";

export type ChatAttachment = components["schemas"]["AttachmentInput"];
export const MAX_FILE_BYTES = 2 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 4 * 1024 * 1024;
export const FILE_TYPES: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  csv: "text/csv",
  txt: "text/plain",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
};
export const ACCEPT_FILES = Object.keys(FILE_TYPES)
  .map((ext) => `.${ext}`)
  .join(",");
export const attachmentSize = (file: ChatAttachment) =>
  Math.floor((file.data.length * 3) / 4) -
  (file.data.endsWith("==") ? 2 : file.data.endsWith("=") ? 1 : 0);
export const fileSize = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.ceil(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export async function readAttachments(
  files: File[],
  existing: ChatAttachment[],
): Promise<ChatAttachment[]> {
  if (
    files.some(
      (file) =>
        file.name.length > 180 ||
        Array.from(file.name).some(
          (c) => c.charCodeAt(0) < 32 || c === "/" || c === "\\",
        ),
    )
  )
    throw new Error(
      "Use file names under 180 characters without paths or control characters.",
    );
  if (files.length + existing.length > 3)
    throw new Error("Attach up to 3 files per message.");
  if (files.some((file) => !file.size || file.size > MAX_FILE_BYTES))
    throw new Error("Each file must be nonempty and at most 2 MB.");
  if (
    files.reduce(
      (sum, file) => sum + file.size,
      existing.reduce((sum, file) => sum + attachmentSize(file), 0),
    ) > MAX_TOTAL_BYTES
  )
    throw new Error("Attachments must total at most 4 MB per message.");
  if (
    files.some(
      (file) => !FILE_TYPES[file.name.split(".").pop()?.toLowerCase() ?? ""],
    )
  )
    throw new Error("Use PDF, DOCX, XLSX, CSV, TXT, PNG, JPEG or WebP files.");
  const added = await Promise.all(
    files.map(async (file) => {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () =>
          reject(
            new Error("This file could not be read. Try attaching it again."),
          );
        reader.readAsDataURL(file);
      });
      return {
        name: file.name,
        media_type: FILE_TYPES[file.name.split(".").pop()!.toLowerCase()],
        data,
      };
    }),
  );
  return [...existing, ...added];
}

export async function draftSignature(
  text: string,
  attachments: ChatAttachment[],
) {
  const bytes = new TextEncoder().encode(JSON.stringify({ text, attachments }));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
