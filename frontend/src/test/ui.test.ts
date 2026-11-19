import { describe, expect, it } from "vitest";
import { formatBytes, formatNumber, difficultyTone, licenseTone } from "../components/ui";

describe("formatting helpers", () => {
  it("formats byte sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatBytes(null)).toBe("—");
  });

  it("formats numbers with grouping", () => {
    expect(formatNumber(20640)).toBe((20640).toLocaleString());
    expect(formatNumber(null)).toBe("—");
  });

  it("maps difficulty to a badge tone", () => {
    expect(difficultyTone("Easy")).toBe("green");
    expect(difficultyTone("Medium")).toBe("amber");
    expect(difficultyTone("Hard")).toBe("red");
  });

  it("maps licence status to a badge tone", () => {
    expect(licenseTone("verified")).toBe("green");
    expect(licenseTone("review-required")).toBe("amber");
    expect(licenseTone(null)).toBe("neutral");
  });
});

describe("readIpynb (.ipynb only)", () => {
  const nb = JSON.stringify({ nbformat: 4, nbformat_minor: 5, metadata: {}, cells: [] });
  it("accepts a notebook and rejects other files", async () => {
    const { readIpynb } = await import("../components/ipynbFile");
    const ok = await readIpynb(new File([nb], "work.ipynb"));
    expect(ok.file_name).toBe("work.ipynb");
    await expect(readIpynb(new File([nb], "work.py"))).rejects.toThrow(/Only .ipynb/);
    await expect(readIpynb(new File(["not json"], "x.ipynb"))).rejects.toThrow(/not JSON/);
    await expect(readIpynb(new File([JSON.stringify({ nbformat: 3, cells: [] })], "x.ipynb"))).rejects.toThrow(/nbformat 4/);
  });
});
