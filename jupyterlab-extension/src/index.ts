/**
 * OpenCS dataset insertion extension.
 *
 * Contract (ADR-005, ADR-008): selecting a dataset inserts a code cell into the
 * active notebook and NEVER executes it. There is exactly one place that could
 * violate this — `insertDatasetCell` — and it explicitly refuses
 * `auto_execute: true`. No kernel `requestExecute` call exists in this file.
 */

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
} from '@jupyterlab/application';
import { IMainMenu } from '@jupyterlab/mainmenu';
import { INotebookTracker } from '@jupyterlab/notebook';
import { Menu, Widget } from '@lumino/widgets';

const PLUGIN_ID = '@opencs/datasets:plugin';
const COMMAND_INSERT = 'opencs:insert-dataset-cell';
const COMMAND_BROWSE = 'opencs:open-dataset-catalogue';
const COMMAND_OPEN_PANEL = 'opencs:catalogue-panel';

/** Wire shape of `GET /datasets/{slug}/snippet` from the backend. */
interface DatasetSnippet {
  dataset_id: string;
  version: number;
  language: string;
  cell_type: string;
  auto_execute: boolean;
  code: string;
  path: string;
  read_only: boolean;
}

interface InsertArgs {
  dataset_id: string;
  version?: number;
  code: string;
  auto_execute?: boolean;
}

interface DatasetSummary {
  slug: string;
  title: string;
  summary: string;
  category: string;
  format: string | null;
  row_count: number | null;
  license_status: string | null;
}

interface DatasetListResponse {
  datasets: DatasetSummary[];
  total: number;
}

/** Where the OpenCS API lives. Same-origin, so the session cookie applies. */
function apiBase(): string {
  const settings = (window as unknown as {
    jupyterlab?: { opencs?: { apiBase?: string } };
  }).jupyterlab?.opencs;
  return settings?.apiBase ?? '/api/v1';
}

/**
 * Fetch the catalogue for one dataset.
 *
 * `credentials: 'include'` sends the OpenCS session cookie, which is the same
 * credential the web app uses. No token is minted here.
 */
async function fetchSnippet(slug: string, version?: number): Promise<DatasetSnippet> {
  const query = version === undefined ? '' : `?version=${version}`;
  const response = await fetch(
    `${apiBase()}/datasets/${encodeURIComponent(slug)}/snippet${query}`,
    { credentials: 'include', headers: { Accept: 'application/json' } }
  );
  if (!response.ok) {
    throw new Error(`Could not load the loading code for "${slug}" (HTTP ${response.status})`);
  }
  return (await response.json()) as DatasetSnippet;
}

async function fetchCatalogue(): Promise<DatasetSummary[]> {
  const response = await fetch(`${apiBase()}/datasets?limit=100`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Could not load the dataset catalogue (HTTP ${response.status})`);
  }
  const body = (await response.json()) as DatasetListResponse;
  return body.datasets ?? [];
}

/**
 * Insert `code` as a new code cell immediately below the active cell.
 *
 * Deliberately does not touch the kernel. The student presses Run.
 */
function insertCodeCell(tracker: INotebookTracker, code: string): void {
  const panel = tracker.currentWidget;
  if (!panel) {
    throw new Error('Open a notebook before inserting a dataset cell.');
  }
  const notebook = panel.content;
  const activeIndex = notebook.activeCellIndex;
  const source = code.endsWith('\n') ? code : `${code}\n`;

  if (!notebook.model) {
    throw new Error('This notebook has no document model.');
  }

  // Insert directly after the active cell and select it. Deliberately does not
  // touch the kernel: the student presses Run.
  notebook.model.sharedModel.insertCell(activeIndex + 1, {
    cell_type: 'code',
    source,
    metadata: { opencs: { inserted: true } }
  });
  notebook.activeCellIndex = activeIndex + 1;
  notebook.mode = 'edit';
}

/** A minimal catalogue panel rendered with DOM nodes (no React dependency). */
class CatalogueWidget extends Widget {
  constructor(private readonly tracker: INotebookTracker) {
    super();
    this.title.label = 'OpenCS Datasets';
    this.title.caption = 'Datasets available to insert into this notebook';
    this.title.closable = true;
    this.addClass('opencs-catalogue');

    const container = document.createElement('div');
    container.className = 'opencs-catalogue-content';
    container.style.padding = '12px';
    container.style.overflowY = 'auto';
    container.style.height = '100%';

    const status = document.createElement('div');
    status.className = 'opencs-catalogue-status';
    status.textContent = 'Loading datasets…';
    container.appendChild(status);
    this.node.appendChild(container);

    void this.render(container, status);
  }

  private async render(container: HTMLDivElement, status: HTMLDivElement): Promise<void> {
    let datasets: DatasetSummary[];
    try {
      datasets = await fetchCatalogue();
    } catch (error) {
      status.textContent =
        error instanceof Error ? error.message : 'Could not load the catalogue.';
      return;
    }
    status.remove();
    if (datasets.length === 0) {
      const empty = document.createElement('div');
      empty.textContent = 'No published datasets.';
      container.appendChild(empty);
      return;
    }

    for (const dataset of datasets) {
      const card = document.createElement('div');
      card.style.border = '1px solid var(--jp-border-color2)';
      card.style.borderRadius = '4px';
      card.style.padding = '10px';
      card.style.marginBottom = '8px';

      const title = document.createElement('div');
      title.textContent = dataset.title;
      title.style.fontWeight = '600';
      card.appendChild(title);

      const meta = document.createElement('div');
      meta.style.fontSize = '12px';
      meta.style.opacity = '0.8';
      meta.style.margin = '2px 0 6px';
      const parts = [dataset.category];
      if (dataset.format) {
        parts.push(dataset.format);
      }
      if (dataset.row_count !== null) {
        parts.push(`${dataset.row_count.toLocaleString()} rows`);
      }
      if (dataset.license_status) {
        parts.push(`licence: ${dataset.license_status}`);
      }
      meta.textContent = parts.join(' · ');
      card.appendChild(meta);

      const summary = document.createElement('div');
      summary.style.fontSize = '12px';
      summary.style.marginBottom = '8px';
      summary.textContent = dataset.summary;
      card.appendChild(summary);

      const button = document.createElement('button');
      button.className = 'jp-mod-styled jp-mod-accept';
      button.textContent = 'Insert cell';
      button.title = 'Insert the loading code as a new cell. It is not executed.';
      button.onclick = async () => {
        button.disabled = true;
        try {
          const snippet = await fetchSnippet(dataset.slug);
          if (snippet.auto_execute) {
            // Contract violation: refuse rather than silently running code.
            throw new Error('Refusing to insert a snippet that requests auto-execution.');
          }
          insertCodeCell(this.tracker, snippet.code);
          button.textContent = 'Inserted';
        } catch (error) {
          button.disabled = false;
          button.textContent = 'Insert cell';
          status.textContent =
            error instanceof Error ? error.message : 'Could not insert the cell.';
          if (!status.isConnected) {
            container.prepend(status);
          }
        }
      };
      card.appendChild(button);
      container.appendChild(card);
    }
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  description:
    'Insert OpenCS dataset loading cells into the active notebook. Cells are never auto-executed.',
  autoStart: true,
  requires: [INotebookTracker, IMainMenu],
  activate: (app: JupyterFrontEnd, tracker: INotebookTracker, mainMenu: IMainMenu) => {
    app.commands.addCommand(COMMAND_INSERT, {
      label: 'Insert dataset cell',
      caption: 'Insert a dataset loading cell into the active notebook (never executed)',
      isEnabled: () => tracker.currentWidget !== null,
      execute: async (args: Partial<InsertArgs>) => {
        const slug = args.dataset_id;
        if (!slug) {
          throw new Error('No dataset selected.');
        }
        // The insert command takes a ready snippet, or fetches one by slug.
        const snippet: DatasetSnippet = args.code
          ? {
              dataset_id: slug,
              version: args.version ?? 0,
              language: 'python',
              cell_type: 'code',
              auto_execute: args.auto_execute ?? false,
              code: args.code,
              path: '',
              read_only: true,
            }
          : await fetchSnippet(slug, args.version);

        // THE CONTRACT: insert only. See ADR-005.
        if (snippet.auto_execute) {
          throw new Error(
            'This snippet requests auto-execution. OpenCS never inserts executable-on-insert cells.'
          );
        }
        insertCodeCell(tracker, snippet.code);
      }
    });

    app.commands.addCommand(COMMAND_OPEN_PANEL, {
      label: 'Open dataset catalogue',
      caption: 'Browse the OpenCS dataset catalogue and insert a loading cell',
      execute: () => {
        const widget = new CatalogueWidget(tracker);
        app.shell.add(widget, 'main');
        app.shell.activateById(widget.id);
      }
    });

    app.commands.addCommand(COMMAND_BROWSE, {
      label: 'Dataset catalogue',
      execute: () => app.commands.execute(COMMAND_OPEN_PANEL)
    });

    const menu = new Menu({ commands: app.commands });
    menu.title.label = 'OpenCS';
    menu.addItem({ command: COMMAND_OPEN_PANEL });
    menu.addItem({ command: COMMAND_INSERT });
    mainMenu.addMenu(menu, false);
  }
};

export default plugin;
export { COMMAND_INSERT, COMMAND_OPEN_PANEL, fetchSnippet, insertCodeCell };
