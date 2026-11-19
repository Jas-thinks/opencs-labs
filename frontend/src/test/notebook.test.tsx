import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { NotebookView, stripAnsi } from "../components/NotebookView";
import type { NotebookDocument } from "../api/types";

/** Student notebook output is untrusted: nothing may execute in the grader's page. */
describe("NotebookView security", () => {
  const hostile: NotebookDocument = {
    cells: [
      { cell_type: "markdown", source: ["# Hi\n", "<img src=x onerror=\"window.pwned=1\"> <script>window.pwned=2</script>"] },
      {
        cell_type: "code",
        source: "df.head()",
        execution_count: 1,
        outputs: [
          {
            output_type: "execute_result",
            data: { "text/html": "<table><tr><td>1</td></tr></table><script>window.pwned=3</script>" },
          },
          {
            output_type: "display_data",
            data: { "image/svg+xml": "<svg xmlns='http://www.w3.org/2000/svg' onload='window.pwned=4'><script>window.pwned=5</script></svg>" },
          },
          { output_type: "display_data", data: { "image/png": "not base64 <script>" } },
          { output_type: "stream", name: "stderr", text: "\u001b[31mred error\u001b[0m" },
        ],
      },
    ],
  };

  it("never puts student HTML or scripts into the page DOM", () => {
    const { container } = render(<NotebookView document={hostile} />);
    // Markdown HTML is shown as text, not parsed.
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img[onerror]")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined();
  });

  it("isolates text/html in a fully sandboxed iframe", () => {
    const { container } = render(<NotebookView document={hostile} />);
    const frame = container.querySelector("iframe");
    expect(frame).not.toBeNull();
    // Empty sandbox attribute = no scripts, no same-origin, no forms, no popups.
    expect(frame!.getAttribute("sandbox")).toBe("");
    expect(frame!.getAttribute("srcdoc")).toContain("<table>");
  });

  it("renders SVG only as an image and drops invalid base64", () => {
    const { container } = render(<NotebookView document={hostile} />);
    const images = [...container.querySelectorAll("img")];
    expect(images).toHaveLength(1);
    expect(images[0].getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(container.querySelector("svg")).toBeNull();
  });

  it("strips ANSI escapes from tracebacks", () => {
    expect(stripAnsi("\u001b[31mred error\u001b[0m")).toBe("red error");
    const { container } = render(<NotebookView document={hostile} />);
    expect(container.textContent).toContain("red error");
    expect(container.textContent).not.toContain("\u001b");
  });

  it("summarises execution and handles empty notebooks", () => {
    const { getByText, rerender } = render(<NotebookView document={hostile} />);
    expect(getByText(/2 cells · 1\/1 code cells executed/)).toBeTruthy();
    rerender(<NotebookView document={{ cells: [] }} />);
    expect(getByText("This notebook has no cells.")).toBeTruthy();
  });
});
