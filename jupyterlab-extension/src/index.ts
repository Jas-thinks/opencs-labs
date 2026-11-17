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

interface OpenCSMetadata {
  notebook_id?: string;
  state_version?: number;
  api_base?: string;
}

function readOpenCSMetadata(panel: unknown): OpenCSMetadata | null {
  const node = panel as
    | {
        content?: { model?: { metadata?: unknown } };
        context?: { model?: { metadata?: unknown } };
      }
    | null;
  const metadata = (node?.content?.model?.metadata ?? node?.context?.model?.metadata) as
    | { opencs?: OpenCSMetadata; get?: (key: string) => unknown }
    | undefined;
  if (!metadata) {
    return null;
  }
  if (typeof metadata.get === 'function') {
    const value = metadata.get('opencs') as OpenCSMetadata | undefined;
    if (value) {
      return value;
    }
  }
  return (metadata.opencs as OpenCSMetadata | undefined) ?? null;
}

/**
 * Snapshot/autosave + heartbeat for the open notebook.
 *
 * The backend is authoritative: every save carries the `base_version` this
 * client last saw. A 409 means another writer advanced the version; we refresh
 * the base and retry once. Identical content is an idempotent no-op server-side.
 */
class NotebookStateSync {
  private panel: any = null;
  private notebookId: string | null = null;
  private stateVersion = 0;
  private base = apiBase();
  private shared: any = null;
  private saveTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private inFlight = false;
  private pending = false;

  private readonly onChange = () => this.schedule(2000);
  private readonly onCurrentChanged = () => this.attach();

  constructor(private readonly tracker: INotebookTracker) {
    this.tracker.currentChanged.connect(this.onCurrentChanged);
    this.attach();
    this.heartbeatTimer = setInterval(() => {
      void this.heartbeat();
    }, 30000);
  }

  private attach(): void {
    if (this.shared) {
      try {
        this.shared.changed.disconnect(this.onChange);
      } catch {
        // already disconnected
      }
      this.shared = null;
    }
    this.panel = this.tracker.currentWidget;
    this.notebookId = null;
    if (!this.panel) {
      return;
    }
    const opencs = readOpenCSMetadata(this.panel);
    if (!opencs?.notebook_id) {
      return;
    }
    this.notebookId = opencs.notebook_id;
    this.stateVersion = Number(opencs.state_version ?? 0);
    this.base = opencs.api_base || apiBase();
    this.shared = this.panel.content?.model?.sharedModel ?? null;
    if (this.shared?.changed?.connect) {
      this.shared.changed.connect(this.onChange);
    }
    void this.heartbeat();
  }

  private document(): Record<string, unknown> | null {
    try {
      const model = this.panel?.content?.model ?? this.panel?.context?.model;
      if (model && typeof model.toJSON === 'function') {
        return model.toJSON() as Record<string, unknown>;
      }
    } catch {
      // fall through
    }
    return null;
  }

  private schedule(delay = 2000): void {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
    }
    this.saveTimer = setTimeout(() => {
      this.saveTimer = null;
      void this.flush();
    }, delay);
  }

  private async put(document: Record<string, unknown>): Promise<Response> {
    return fetch(`${this.base}/notebooks/${encodeURIComponent(this.notebookId!)}/autosave`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ base_version: this.stateVersion, document })
    });
  }

  private async flush(): Promise<void> {
    if (!this.notebookId) {
      return;
    }
    if (this.inFlight) {
      this.pending = true;
      return;
    }
    const document = this.document();
    if (!document) {
      return;
    }
    this.inFlight = true;
    try {
      let response = await this.put(document);
      if (response.status === 409) {
        const body = (await response.json()) as {
          error?: { details?: { current_version?: number } };
        };
        this.stateVersion = Number(
          body?.error?.details?.current_version ?? this.stateVersion
        );
        response = await this.put(document);
      }
      if (response.ok) {
        const body = (await response.json()) as { version?: number };
        if (typeof body.version === 'number') {
          this.stateVersion = body.version;
        }
      }
    } catch {
      // Offline or the backend is restarting; the watcher is the backstop.
    } finally {
      this.inFlight = false;
      if (this.pending) {
        this.pending = false;
        this.schedule(500);
      }
    }
  }

  private async heartbeat(): Promise<void> {
    if (!this.notebookId) {
      return;
    }
    try {
      await fetch(
        `${this.base}/notebooks/${encodeURIComponent(this.notebookId)}/heartbeat`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ client: 'jupyterlab' })
        }
      );
    } catch {
      // Presence is best-effort; never surface this to the student.
    }
  }

  dispose(): void {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
    }
    if (this.shared) {
      try {
        this.shared.changed.disconnect(this.onChange);
      } catch {
        // already disconnected
      }
    }
    this.tracker.currentChanged.disconnect(this.onCurrentChanged);
  }
}

/** Ask JupyterLab's document manager to autosave every 30 seconds. */
async function configureAutosave(registry: any): Promise<void> {
  if (!registry?.load) {
    return;
  }
  try {
    const settings = await registry.load('@jupyterlab/docmanager-extension:plugin');
    if (settings.get('autosaveInterval').composite !== 30) {
      await settings.set('autosaveInterval', 30);
    }
  } catch {
    // Older/newer JupyterLab versions may not expose this setting; the
    // extension's own autosave and the backend watcher still cover it.
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  description:
    'Insert OpenCS dataset loading cells into the active notebook. Cells are never auto-executed.',
  autoStart: true,
  requires: [INotebookTracker, IMainMenu],
  optional: ['@jupyterlab/settingregistry:settingRegistry'],
  activate: (
    app: JupyterFrontEnd,
    tracker: INotebookTracker,
    mainMenu: IMainMenu,
    settingRegistry?: any
  ) => {
    void configureAutosave(settingRegistry);

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

    const sync = new NotebookStateSync(tracker);
    app.shell.disposed.connect(() => sync.dispose());
  }
};

export default plugin;
export {
  COMMAND_INSERT,
  COMMAND_OPEN_PANEL,
  NotebookStateSync,
  fetchSnippet,
  insertCodeCell
};
