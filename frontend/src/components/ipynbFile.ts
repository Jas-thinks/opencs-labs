import type { NotebookDocument } from "../api/types";

/** Same limit as the server (OPENCE_NOTEBOOK_UPLOAD_MAX_BYTES); checked first to fail fast. */
export const MAX_NOTEBOOK_BYTES = 5 * 1024 * 1024;

export interface IpynbFile {
  file_name: string;
  notebook: NotebookDocument;
}

/**
 * Read a user-chosen file as a Jupyter notebook. Only .ipynb is accepted.
 * This is a convenience check; the server re-validates everything.
 */
export async function readIpynb(file: File): Promise<IpynbFile> {
  if (!file.name.toLowerCase().endsWith(".ipynb")) {
    throw new Error("Only .ipynb notebook files can be uploaded.");
  }
  if (file.size > MAX_NOTEBOOK_BYTES) {
    throw new Error(`This notebook is ${(file.size / 1048576).toFixed(1)} MB; the limit is 5 MB. Clear large outputs and try again.`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(await readText(file));
  } catch {
    throw new Error("This file is not a valid notebook (it is not JSON).");
  }
  const doc = parsed as NotebookDocument;
  if (!doc || typeof doc !== "object" || !Array.isArray(doc.cells) || doc.nbformat !== 4) {
    throw new Error("This file is not a Jupyter notebook in nbformat 4.");
  }
  return { file_name: file.name, notebook: doc };
}

export function formatKb(bytes: number | null | undefined): string {
  if (!bytes) return "";
  return bytes < 1048576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}

/** File.text() is missing in some older browsers (and jsdom); FileReader works everywhere. */
function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file"));
    reader.readAsText(file);
  });
}
