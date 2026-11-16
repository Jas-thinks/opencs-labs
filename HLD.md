# OpenCS Labs --- High-Level Design (HLD)

**Document status:** Architecture baseline / implementation source of
truth\
**Version:** 1.0\
**Date:** 16 November 2026\
**Project:** OpenCS Labs\
**Primary objective:** A multi-user platform for teaching and practicing
Data Analysis and Data Science through persistent Jupyter notebooks.

------------------------------------------------------------------------

## 1. Executive Summary

OpenCS Labs is a browser-based learning and computation platform where
students learn Data Analysis and Data Science, practice concepts using
guided exercises, and work independently in Jupyter notebooks.

It combines three closely integrated experiences:

1.  **Learn:** Structured, interactive teaching modules that explain
    concepts step by step, show real datasets and visualizations, and
    connect explanations to executable notebook code.
2.  **Practice:** A dedicated practice area with exercises, tasks,
    hints, starter code/notebooks, datasets, and feedback.
3.  **Notebook Workspace:** New and previous Jupyter notebooks, a
    dataset catalogue, and a consistent Python environment with
    data-analysis and machine-learning libraries.

The platform must support a class of up to **600 enrolled students** and
a target peak of **400 concurrent active notebook users**. Notebook
execution is isolated per student and scheduled across a multi-node
compute cluster.

The central architecture decision is to use **JupyterHub + KubeSpawner +
Kubernetes**, rather than implementing notebook server or kernel
lifecycle management from scratch.

### 1.1 Product definition

OpenCS Labs is not intended to be a general-purpose LMS. Its core is a
teaching-oriented Data Analysis workspace backed by real notebook
execution.

A student should be able to:

-   Learn a topic through a guided lesson.
-   See a concept explained with a table, chart, animation/step
    sequence, or worked example.
-   Open the corresponding dataset in a notebook.
-   Click a dataset in the catalogue and insert a ready-to-run code cell
    into the active notebook.
-   Run that cell themselves and continue analysis.
-   Open a new notebook or resume a previously saved notebook.
-   Practice through structured exercises using the same libraries and
    notebook environment.
-   Save work and return to it later.

### 1.2 Scale targets

  -----------------------------------------------------------------------
  Measure                                                          Target
  ------------------------------ ----------------------------------------
  Maximum enrolled students in                                        600
  one class                      

  Peak concurrent notebook users                                      400

  Notebook model                  One isolated single-user Jupyter server
                                                       per active student

  Python environment                Centrally built, versioned and pinned
                                                                    image

  Dataset source                        Centrally managed, locally hosted
                                                          dataset library

  Notebook persistence                     Persistent per-student storage

  Compute model                  Kubernetes schedules independent student
                                            workloads across worker nodes

  Initial distributed-compute     Distribute independent student sessions
  requirement                                                across nodes

  Advanced distributed                          Optional later capability
  dataframe/ML inside one        
  notebook                       
  -----------------------------------------------------------------------

**Important:** "400 concurrent users" is a capacity target to validate
through load testing. It is not a claim that a particular number of
machines is sufficient. Final node count depends on measured CPU,
memory, storage I/O, notebook startup and workload profiles.

------------------------------------------------------------------------

## 2. Goals, Non-Goals and Scope

### 2.1 In scope --- must be delivered

#### A. Learning / Teaching section

-   Structured Data Analysis and Data Science learning paths.
-   Beginner-first explanations with no unexplained jumps.
-   Concept → small example → visual explanation → executable code →
    worked result.
-   Interactive tables and charts where useful.
-   Step-by-step demonstrations of data transformations.
-   Explain common errors and how to fix them.
-   Link each lesson to the relevant dataset and notebook activity.
-   "Open in Notebook" action to continue the lesson hands-on.
-   Progress tracking at lesson/topic level.
-   Responsive student-facing interface.

The teaching experience should follow the successful educational pattern
used in the NOVA compiler project: **Explore → Understand → Execute →
Inspect → Debug → Practice**. For OpenCS Labs, the equivalent Data
Analysis learning flow is described in Section 7.

#### B. Practice section

-   Dedicated practice page, separate from the lesson catalogue.
-   Topic-wise and difficulty-wise exercises.
-   Each exercise can include:
    -   Problem statement and learning objective.
    -   Dataset association.
    -   Starter code or starter notebook.
    -   Expected task/output description.
    -   Progressive hints.
    -   Example or reference solution, released according to course
        policy.
    -   Automated checks where the exercise has deterministic
        requirements.
    -   Completion/progress state.
-   "Practice in Notebook" opens a student's own isolated notebook with
    the starter content.
-   Practice execution must use the same pinned environment as lessons
    and normal notebooks.
-   Practice must not require a separate, inconsistent Python runtime.

#### C. Notebook workspace

-   Create a new notebook.
-   List previous notebooks belonging to the authenticated student.
-   Open, edit, save, rename and delete notebooks, subject to
    confirmation/policy.
-   JupyterLab notebook editor and terminal capabilities as configured
    by administrators.
-   Run, interrupt and restart kernels.
-   Download notebook (`.ipynb`) and optionally export to `.py`/HTML.
-   Notebook files and outputs persist independently of kernel memory.
-   Students cannot access another student's notebooks or files.

#### D. Dataset catalogue and notebook integration

-   Searchable/browsable catalogue of centrally stored datasets.
-   Dataset detail/preview: description, file format, size,
    columns/schema, sample rows and learning tags.
-   Clicking a dataset inserts a loading code cell into the currently
    active notebook.
-   Clicking must **not** execute the code automatically.
-   Student explicitly runs the inserted cell.
-   Dataset files are centrally managed and read-only to students.
-   Common datasets are served locally, not downloaded from Kaggle or
    other public websites at runtime.
-   Dataset versions and checksums are tracked.

#### E. Python library support

The standard image must include a tested and pinned set of libraries:

  Area                         Libraries
  ---------------------------- -----------------------------------------------------
  Notebook runtime             JupyterLab, IPython, ipykernel
  Numerical computing          NumPy
  Data manipulation            pandas
  Visualization                Matplotlib, Seaborn, Plotly
  Scientific computing         SciPy
  Statistics                   statsmodels
  Classical machine learning   scikit-learn
  Tree ensembles               Random Forest through scikit-learn
  Gradient boosting            XGBoost
  File formats                 openpyxl, pyarrow, fastparquet (as selected/tested)
  Database access              SQLAlchemy, SQLite support

Exact versions must be pinned in a lock file and recorded in each image
release. The table identifies supported library families, not permission
for students to upgrade packages independently.

#### F. Platform operations

-   Authentication and authorization.
-   Per-user notebook server lifecycle.
-   CPU/memory quotas and limits.
-   Idle shutdown and on-demand startup.
-   Centralized logging and metrics.
-   Admin ability to publish lesson content, datasets and practice
    exercises.
-   Backup and recovery procedures.

### 2.2 Explicit non-goals for the first release

-   Full LMS features such as attendance, timetable, fee management or a
    complete gradebook.
-   Social network, chat or discussion forum.
-   Arbitrary student-created Docker images.
-   Student-controlled `pip install` into the shared base environment.
-   Running arbitrary student code in the FastAPI application process.
-   Building a custom Jupyter server, notebook protocol or kernel
    manager.
-   Distributed training across a GPU cluster.
-   Dask/Ray cluster provisioning for every student by default.
-   Multiple programming languages in the initial release.
-   Replacing JupyterLab with a custom notebook editor.

These may be considered later only when a concrete requirement justifies
them.

------------------------------------------------------------------------

## 3. Users and Primary User Journeys

### 3.1 Roles

  -----------------------------------------------------------------------
  Role                                Permissions
  ----------------------------------- -----------------------------------
  Student                             View published
                                      lessons/datasets/practice; create
                                      and manage own notebooks; execute
                                      code in own environment

  Instructor/content author           Create and publish lessons,
                                      exercises and dataset metadata;
                                      view course-level progress if
                                      authorized

  Platform administrator              Manage users, course configuration,
                                      image versions, resource profiles,
                                      datasets, cluster policy and
                                      monitoring
  -----------------------------------------------------------------------

The initial product can have a simple instructor/admin role. It does not
need a sophisticated institution-wide role hierarchy.

### 3.2 Student journey: Learn

1.  Student signs in.
2.  Student opens the Learning section.
3.  Student selects a topic, for example "Pandas DataFrames".
4.  The lesson explains the concept with a small example and visual
    output.
5.  Student inspects a transformation or chart.
6.  Student selects **Open in Notebook**.
7.  The platform launches or reuses the student's Jupyter server.
8.  A lesson notebook or code cell is opened with the relevant dataset
    and instructions.
9.  Student executes and experiments.
10. Lesson progress is saved.

### 3.3 Student journey: Dataset to notebook

1.  Student opens New Notebook or an existing notebook.
2.  Student opens the Load Dataset catalogue.
3.  Student searches for or selects a dataset, e.g. Iris.
4.  The frontend requests a dataset loading snippet from the
    backend/catalogue.
5.  The snippet is inserted into the active notebook as a new code cell.
6.  The cell is not automatically executed.
7.  Student presses Run.
8.  The student's own kernel reads the centrally stored, read-only
    dataset.
9.  The resulting DataFrame is available in that notebook's Python
    namespace.

Example inserted cell:

``` python
import pandas as pd

df = pd.read_csv("/opt/opencs/datasets/iris/v1/iris.csv")
df.head()
```

The exact path is generated from trusted catalogue metadata. The
frontend must not construct arbitrary filesystem paths from untrusted
user input.

### 3.4 Student journey: Previous notebook

1.  Student opens Previous Notebooks.
2.  Backend returns only notebooks owned by that student.
3.  Student selects a notebook.
4.  The platform launches/reuses the student's notebook server.
5.  JupyterLab opens the saved `.ipynb` file.
6.  Student can continue editing and executing it.

A saved notebook contains code, markdown, outputs and metadata. A
notebook file does **not** preserve the live Python process, variables
or in-memory DataFrames. After a kernel restart, the student reruns the
required cells.

### 3.5 Student journey: Practice

1.  Student opens Practice.
2.  Student filters by topic and difficulty.
3.  Student opens an exercise.
4.  The exercise shows its objective, instructions, associated dataset
    and hints.
5.  Student clicks **Practice in Notebook**.
6.  The platform creates a private starter notebook from a published
    template.
7.  The student's Jupyter server opens the starter notebook.
8.  Student writes and runs code.
9.  If the exercise supports automated evaluation, the student
    submits/runs checks.
10. The platform returns useful feedback and records completion.

------------------------------------------------------------------------

## 4. Functional Requirements

IDs are used to make implementation and testing traceable.

### 4.1 Authentication and user management

-   **FR-001:** Authenticate students and staff using the institution's
    supported identity provider (OIDC/LDAP) where available.
-   **FR-002:** Assign each authenticated user a stable internal user
    ID.
-   **FR-003:** Enforce role-based permissions.
-   **FR-004:** Associate students with a course/class.
-   **FR-005:** Ensure every notebook, practice attempt and personal
    file is scoped to its owner.

### 4.2 Learning

-   **FR-010:** List published learning paths, modules and lessons.
-   **FR-011:** Render lesson text, code examples, tables, charts and
    step-by-step demonstrations.
-   **FR-012:** Associate lessons with datasets and practice exercises.
-   **FR-013:** Launch a lesson's notebook activity.
-   **FR-014:** Track lesson completion/progress.
-   **FR-015:** Allow authorized instructors to create, edit, preview
    and publish lesson content.

### 4.3 Practice

-   **FR-020:** List and filter exercises by topic and difficulty.
-   **FR-021:** Show problem statements, dataset references and hints.
-   **FR-022:** Create a private starter notebook for a student.
-   **FR-023:** Launch the starter notebook in the student's Jupyter
    environment.
-   **FR-024:** Run automated checks in an isolated execution context
    when configured.
-   **FR-025:** Save practice attempt status and feedback.
-   **FR-026:** Prevent students from reading hidden test cases or
    unreleased solutions through the browser/API.

### 4.4 Notebook workspace

-   **FR-030:** Create a new `.ipynb` notebook.
-   **FR-031:** List previous notebooks for the authenticated student.
-   **FR-032:** Open, rename, save and delete owned notebooks.
-   **FR-033:** Start, stop, interrupt and restart a notebook
    server/kernel.
-   **FR-034:** Preserve notebook files on persistent storage.
-   **FR-035:** Support notebook download/export.
-   **FR-036:** Apply a centrally selected environment image to student
    sessions.

### 4.5 Dataset catalogue

-   **FR-040:** List and search published datasets.
-   **FR-041:** Show dataset details, schema, preview and tags.
-   **FR-042:** Return a safe, ready-to-insert loading snippet for a
    dataset.
-   **FR-043:** Insert the snippet into the active notebook as a code
    cell.
-   **FR-044:** Never auto-execute a cell as a side effect of clicking a
    dataset.
-   **FR-045:** Provide datasets from managed local storage.
-   **FR-046:** Preserve old dataset versions for reproducibility where
    required.
-   **FR-047:** Restrict students to read-only access to shared source
    datasets.

### 4.6 Compute and operations

-   **FR-050:** Run a separate notebook server/pod for each active
    student.
-   **FR-051:** Enforce CPU, memory, ephemeral storage and process
    limits.
-   **FR-052:** Schedule user pods across Kubernetes worker nodes.
-   **FR-053:** Shut down idle servers according to policy.
-   **FR-054:** Queue or reject new launches safely when capacity is
    exhausted.
-   **FR-055:** Collect metrics and logs without exposing one student's
    notebook content to another student.
-   **FR-056:** Support controlled image upgrades and rollback.

------------------------------------------------------------------------

## 5. Non-Functional Requirements

  ------------------------------------------------------------------------
  ID                      Requirement             Design response
  ----------------------- ----------------------- ------------------------
  NFR-001                 600 enrolled students   Support account/class
                                                  metadata for at least
                                                  this class size

  NFR-002                 400 concurrent active   Multi-node Kubernetes
                          notebook users          capacity, admission
                                                  control and load testing

  NFR-003                 Isolation               Separate user pods,
                                                  service accounts,
                                                  storage and network
                                                  policy

  NFR-004                 Environment consistency Immutable versioned
                                                  image, pinned
                                                  dependencies

  NFR-005                 Notebook durability     Persistent per-user
                                                  storage and backups

  NFR-006                 Dataset availability    Local central object
                                                  store plus read-only
                                                  serving/cache layer

  NFR-007                 Maintainability         Modular backend and
                                                  infrastructure-as-code

  NFR-008                 Observability           Metrics, logs,
                                                  traces/alerts where
                                                  practical

  NFR-009                 Recoverability          Pod rescheduling,
                                                  persistent data and
                                                  tested restore
                                                  procedures

  NFR-010                 Usability               Simple learning,
                                                  practice and notebook
                                                  navigation

  NFR-011                 Security                Authentication,
                                                  authorization, least
                                                  privilege and sandboxing

  NFR-012                 Reproducibility         Record image and dataset
                                                  versions in
                                                  notebook/activity
                                                  metadata
  ------------------------------------------------------------------------

### 5.1 Proposed service objectives

These are initial targets to validate, not existing measured guarantees:

-   Notebook launch: define and measure p50/p95 from launch click to
    JupyterLab readiness.
-   Dataset catalogue: p95 response below 500 ms for normal catalogue
    queries under expected load.
-   Dataset snippet insertion: immediate client-side insertion after a
    successful catalogue response.
-   Notebook persistence: saved notebook files survive pod deletion and
    rescheduling.
-   Platform availability: establish a target with the
    course/institution before production rollout.
-   Capacity: sustain 400 representative concurrent sessions in a
    documented load test without uncontrolled failures.

Do not claim a notebook startup target until image pull time, storage
attach time and actual cluster performance have been measured.

------------------------------------------------------------------------

## 6. High-Level Architecture

### 6.1 Architecture principles

1.  **Use mature notebook infrastructure:** JupyterHub manages user
    servers; do not reimplement it.
2.  **Separate control plane and compute plane:** Platform APIs and
    JupyterHub control sessions; student pods execute code.
3.  **One isolated server per active student:** No shared Python process
    or shared kernel between students.
4.  **Immutable environments:** Every student session for a course/image
    release uses the same tested image digest.
5.  **Persistent work, disposable compute:** Notebook files persist;
    user pods and kernels can be recreated.
6.  **Central datasets, read-only consumption:** Keep canonical datasets
    in centrally managed storage.
7.  **Modular monolith first:** Keep the OpenCS application backend
    modular; do not split every feature into a microservice.
8.  **Scale based on measurements:** Use load tests and observed
    workload profiles to size the cluster.

### 6.2 Logical component diagram

``` mermaid
flowchart TB
    U[Students / Instructors] --> WEB[React + TypeScript Web App]
    WEB --> ING[HTTPS Ingress / Reverse Proxy]
    ING --> API[FastAPI Application API]
    ING --> HUB[JupyterHub Proxy / Hub]

    API --> PG[(PostgreSQL)]
    API --> REDIS[(Redis - optional cache)]
    API --> OBJ[(MinIO Object Storage)]
    API --> CONTENT[Learning / Practice Content]

    HUB --> SPAWNER[KubeSpawner]
    SPAWNER --> K8S[Kubernetes API / Scheduler]

    K8S --> P1[Student Notebook Pod A]
    K8S --> P2[Student Notebook Pod B]
    K8S --> P3[Student Notebook Pod ...]
    K8S --> PN[Student Notebook Pod N]

    P1 --> JL1[JupyterLab + Python Kernel]
    P2 --> JL2[JupyterLab + Python Kernel]
    P3 --> JL3[JupyterLab + Python Kernel]
    PN --> JLN[JupyterLab + Python Kernel]

    P1 --> HOME[(Per-user Persistent Volume)]
    P2 --> HOME
    P3 --> HOME
    PN --> HOME

    P1 --> DATA[Read-only Dataset Volume / Node Cache]
    P2 --> DATA
    P3 --> DATA
    PN --> DATA

    OBJ --> DATA
    REG[Private Container Registry] --> P1
    REG --> P2
    REG --> P3
    REG --> PN

    K8S --> OBS[Prometheus / Grafana / Logs]
```

### 6.3 Component responsibilities

  -------------------------------------------------------------------------
  Component                 Responsibility          Must not own
  ------------------------- ----------------------- -----------------------
  React frontend            Learning UI, practice   Kernel execution or
                            UI, notebook launch     storage authorization
                            controls, dataset       decisions
                            catalogue               

  FastAPI backend           Users/course metadata,  Executing arbitrary
                            content APIs, dataset   student Python
                            catalogue, practice     
                            metadata, notebook      
                            launch orchestration    

  PostgreSQL                Durable relational      Notebook binary/object
                            metadata                storage

  Redis                     Optional cache, rate    Source of truth for
                            limits, short-lived     user data
                            coordination            

  JupyterHub                Authentication          Learning content
                            integration and user    database
                            notebook server         
                            lifecycle               

  Configurable HTTP Proxy   Route browser traffic   Student identity policy
                            to the correct user     
                            server                  

  KubeSpawner               Create/stop/poll        Course content
                            student notebook pods   management

  Kubernetes                Scheduling, isolation   Notebook file
                            primitives, resource    persistence by itself
                            enforcement             

  JupyterLab                Notebook editing and    Cross-student session
                            user-facing execution   management

  Python kernel             Execute code inside one Shared global execution
                            user's pod              

  MinIO                     Canonical object        Transactional metadata
                            storage for datasets,   
                            content assets and      
                            backups                 

  Dataset serving/cache     Make approved datasets  User notebook storage
  layer                     available locally and   
                            read-only               

  PostgreSQL-backed content Store lesson/practice   Live notebook process
  service                   definitions and         state
                            progress                

  Prometheus/Grafana/Loki   Metrics, dashboards and Student content
                            logs                    authorization
  -------------------------------------------------------------------------

### 6.4 Control plane vs data plane

**Control plane:** - React application and FastAPI APIs. -
Authentication/authorization. - JupyterHub. - KubeSpawner. - Kubernetes
API and scheduler. - PostgreSQL and configuration services.

**Data/compute plane:** - Student notebook pods. - Jupyter servers and
Python kernels. - Student notebook volumes. - Dataset read/cache
layer. - CPU and memory consumed by notebook code.

This separation is essential. A spike in notebook computation should not
block the application API or the learning catalogue.

------------------------------------------------------------------------

## 7. Teaching Experience --- NOVA-Inspired Learning Model

The teaching section is a core product feature, not a static
documentation page.

The NOVA compiler project used a learning pattern where students could
explore a concept, execute it, inspect intermediate representations,
debug it and practice. OpenCS Labs should translate that educational
approach into Data Analysis.

### 7.1 OpenCS learning loop

**Explore → Understand → Inspect → Execute → Visualize → Debug →
Practice**

  -----------------------------------------------------------------------
  Stage                   Student experience      Example: Missing values
  ----------------------- ----------------------- -----------------------
  Explore                 See a real dataset and  A table containing
                          the problem             missing cells

  Understand              Learn what missing      Missing vs zero vs
                          values mean and why     unknown
                          they matter             

  Inspect                 Inspect rows, columns,  `df.info()`,
                          types and summary       `df.isna().sum()`

  Execute                 Run a small             `df.dropna()` or
                          transformation          `df.fillna()`

  Visualize               Compare before and      Missing-value
                          after                   chart/table

  Debug                   Understand errors and   String column treated
                          incorrect assumptions   as numeric

  Practice                Solve a related         Clean a new dataset
                          exercise independently  
  -----------------------------------------------------------------------

The same lesson pattern should be reusable across topics.

### 7.2 Learning section information architecture

``` text
Learn
├── Data Analysis Foundations
│   ├── What is Data Analysis?
│   ├── Data types and tabular data
│   ├── CSV, JSON and Excel
│   └── Questions, hypotheses and data quality
├── Python for Data Analysis
│   ├── Python essentials for analysis
│   ├── NumPy arrays
│   └── Pandas Series and DataFrames
├── Data Cleaning
│   ├── Missing values
│   ├── Duplicates
│   ├── Incorrect data types
│   └── Outliers and inconsistent values
├── Exploratory Data Analysis (EDA)
│   ├── Shape, columns and data types
│   ├── Descriptive statistics
│   ├── Grouping and aggregation
│   └── Relationships and correlation
├── Data Visualization
│   ├── Histograms and distributions
│   ├── Bar and line charts
│   ├── Scatter plots
│   ├── Box plots
│   └── Choosing the right chart
├── Statistics for Data Analysis
│   ├── Mean, median and variance
│   ├── Probability and distributions
│   ├── Sampling and confidence intervals
│   └── Hypothesis testing
└── Introductory Machine Learning
    ├── Train/test split
    ├── Regression and classification
    ├── Decision trees and Random Forest
    ├── XGBoost
    └── Evaluation metrics and overfitting
```

The sequence is a proposed curriculum. Instructors should be able to
publish/reorder modules without code changes.

### 7.3 Lesson page design

A lesson should have:

1.  **Learning objective:** What the student should be able to do.
2.  **Concept explanation:** Beginner-friendly explanation with
    terminology defined.
3.  **Small example:** A compact table or dataset.
4.  **Visual explanation:** Chart, transformation view or step-by-step
    table.
5.  **Code demonstration:** Syntax-highlighted Python code.
6.  **Expected output:** Show what the code produces.
7.  **Common mistakes:** Explain likely errors and their causes.
8.  **Try it yourself:** A runnable notebook activity.
9.  **Practice link:** A related exercise.
10. **Progress state:** Not started / in progress / completed.

### 7.4 Interactive teaching visualizations

Use visualizations only when they improve understanding. Examples:

-   DataFrame explorer: rows, columns, data types and null counts.
-   Before/after data cleaning comparison.
-   GroupBy aggregation: show which rows are grouped and how the result
    is calculated.
-   Histogram: show how bin size changes the distribution.
-   Correlation matrix/heatmap: explain what correlation does and does
    not mean.
-   Train/test split: visualize the partition.
-   Decision tree: show a path through splits.
-   Random Forest: illustrate multiple trees and voting/averaging.
-   XGBoost: explain sequential boosting at a conceptual level.
-   Model evaluation: confusion matrix, precision, recall, F1 and
    regression error.

Visuals should be tied to the exact concept and use consistent sample
data with the notebook lesson.

### 7.5 Teaching execution model

Lesson examples should use the same supported environment as student
notebooks.

Two types of content are allowed:

-   **Static/interactive lesson examples:** Precomputed outputs or safe
    client-side visualizations for quick explanation.
-   **Notebook-backed activities:** Real Python code executed in the
    student's isolated Jupyter kernel.

Do not execute student code inside the FastAPI process or the frontend
server.

------------------------------------------------------------------------

## 8. Practice Section Design

Practice is a separate destination in the main navigation.

### 8.1 Practice catalogue

Students can browse exercises by:

-   Topic.
-   Difficulty: Easy / Medium / Hard.
-   Skill: pandas, cleaning, EDA, visualization, statistics, ML.
-   Dataset.
-   Completion state.

### 8.2 Exercise model

Each exercise should define:

``` json
{
  "id": "pandas-missing-values-01",
  "title": "Handle Missing Values",
  "topic": "Data Cleaning",
  "difficulty": "Easy",
  "objective": "Identify and handle missing values",
  "dataset_id": "titanic-v1",
  "starter_notebook": "templates/missing-values-starter.ipynb",
  "hints": [
    "Inspect missing values by column.",
    "Try isna().sum() before choosing a strategy."
  ],
  "evaluation": {
    "type": "notebook_check",
    "enabled": true
  }
}
```

This is an illustrative content schema; production validation and
hidden-test handling must be implemented.

### 8.3 Exercise execution

``` mermaid
sequenceDiagram
    participant S as Student
    participant UI as OpenCS UI
    participant API as FastAPI
    participant DB as PostgreSQL
    participant HUB as JupyterHub
    participant K as Student Kernel

    S->>UI: Open exercise
    UI->>API: GET exercise details
    API->>DB: Read published exercise
    DB-->>API: Exercise metadata
    API-->>UI: Instructions, hints, dataset and template
    S->>UI: Practice in Notebook
    UI->>API: Create practice attempt
    API->>DB: Save attempt metadata
    UI->>HUB: Launch/open notebook server
    HUB-->>UI: User server URL/status
    UI->>K: Open private starter notebook
    S->>K: Write and run solution
    S->>UI: Request evaluation
    UI->>API: Submit attempt/check request
    API->>K: Trigger isolated evaluation workflow
    K-->>API: Check result
    API->>DB: Save result/progress
    API-->>UI: Feedback
```

### 8.4 Automated evaluation and security

-   Do not execute submitted code inside FastAPI.
-   Run checks in the student's isolated pod only for low-risk feedback,
    or preferably in a separate short-lived grading sandbox for
    authoritative evaluation.
-   Hidden tests and reference solutions must not be placed in a
    student-readable directory or sent to the browser.
-   Apply CPU, memory, execution-time and output-size limits.
-   Do not trust a student-supplied score or completion flag.
-   Store attempt metadata and evaluation results separately from
    notebook files.
-   For exercises without deterministic checks, use instructor-defined
    completion or rubric-based feedback rather than pretending that
    arbitrary analysis has one correct answer.

------------------------------------------------------------------------

## 9. Notebook Workspace Design

### 9.1 Main navigation

``` text
OpenCS Labs
├── Learn
├── Practice
└── Notebook Workspace
    ├── New Notebook
    ├── Previous Notebooks
    └── Load Dataset (available inside workspace)
```

Keep the primary product simple. Do not add unrelated LMS navigation.

### 9.2 New notebook

1.  Student clicks New Notebook.
2.  Backend checks authentication and permissions.
3.  Frontend requests the student's Jupyter server.
4.  If a server is already running, reuse it.
5.  Otherwise JupyterHub asks KubeSpawner to create a pod.
6.  Kubernetes schedules the pod.
7.  JupyterLab opens a new notebook in the student's home directory.
8.  Notebook is saved to persistent storage.

### 9.3 Previous notebooks

-   List notebook files from the authenticated user's home directory or
    an indexed metadata service.
-   Never accept a raw filesystem path from the browser.
-   Use a server-side user-to-storage mapping.
-   Validate ownership before open, rename, delete or download.
-   Handle deleted/moved files and stale metadata gracefully.
-   Save notebook metadata such as title, created time and last modified
    time if an index is maintained.

### 9.4 Kernel lifecycle

A Jupyter server can have one or more kernels. The default user
experience should start with a standard Python kernel.

-   Each student's kernel runs inside that student's notebook pod.
-   A kernel restart clears in-memory variables but does not delete the
    saved notebook.
-   A notebook server restart recreates the runtime from the same image
    version.
-   A stopped pod must not be treated as a saved notebook.
-   Persistent storage is independent of kernel process memory.

------------------------------------------------------------------------

## 10. Dataset Library and Storage Architecture

### 10.1 Dataset library objectives

-   Host classic teaching datasets locally.
-   Provide predictable file paths and formats.
-   Avoid external runtime downloads.
-   Keep original datasets immutable.
-   Make dataset loading easy for beginners.
-   Support versioning, metadata and checksums.
-   Serve many students without creating 400 redundant downloads from
    the internet.

### 10.2 Initial dataset catalogue

Candidate datasets (verify licensing, provenance, size and
redistribution terms before publishing):

  Dataset               Teaching use                               Typical format
  --------------------- ------------------------------------------ ----------------
  Iris                  Classification, EDA, visualization         CSV
  Titanic               Missing values, cleaning, classification   CSV
  Wine Quality          Statistics, classification/regression      CSV
  California Housing    Regression, feature analysis               CSV
  Palmer Penguins       EDA, visualization, classification         CSV
  Diabetes dataset      Regression and evaluation                  CSV
  Tips                  GroupBy and visualization                  CSV
  Gapminder sample      Time and country comparisons               CSV
  NYC Taxi sample       Larger-data aggregation                    Parquet/CSV
  Retail/Sales sample   Business analytics and aggregation         CSV

Do not assume every dataset can be redistributed. Keep source, license,
attribution and version metadata.

### 10.3 Storage design

Use a hybrid storage design:

1.  **MinIO:** Canonical object store for original datasets, dataset
    versions, lesson assets, starter notebooks and backups.
2.  **Read-only dataset serving layer:** Expose approved dataset
    versions to notebook pods at a stable path such as
    `/opt/opencs/datasets`.
3.  **Node-local cache or shared read-only filesystem:** Avoid fetching
    the same popular dataset from object storage for every cell
    execution.
4.  **Per-student persistent volume:** Store notebooks and personal
    files.
5.  **PostgreSQL:** Store dataset catalogue metadata, permissions and
    version references.

MinIO is object storage, not automatically a POSIX filesystem. Do not
assume it can safely replace a normal mounted home directory. Use a
Kubernetes CSI-backed persistent volume or a properly operated shared
filesystem for notebook homes.

### 10.4 Dataset path convention

``` text
/opt/opencs/datasets/
├── iris/
│   └── v1/
│       ├── iris.csv
│       └── manifest.json
├── titanic/
│   └── v1/
│       ├── titanic.csv
│       └── manifest.json
├── wine-quality/
│   └── v1/
│       ├── winequality.csv
│       └── manifest.json
└── california-housing/
    └── v1/
        ├── housing.csv
        └── manifest.json
```

The shared mount is read-only inside student pods. Students can copy a
dataset into their home directory if an exercise explicitly requires
modifying a copy.

### 10.5 Dataset manifest

Example:

``` json
{
  "dataset_id": "iris",
  "version": "1",
  "display_name": "Iris Dataset",
  "description": "Classic flower measurements dataset for classification and EDA.",
  "format": "csv",
  "relative_path": "iris/v1/iris.csv",
  "sha256": "<computed-sha256>",
  "size_bytes": 0,
  "columns": [
    "sepal_length",
    "sepal_width",
    "petal_length",
    "petal_width",
    "species"
  ],
  "license": "<verified-license>",
  "source": "<verified-source>",
  "read_only": true
}
```

The hash, size, source and license must be populated from the actual
file and verified source. Never invent them.

### 10.6 Dataset click-to-cell integration

This is a critical product requirement.

**Expected behaviour:**

-   The dataset catalogue is available inside the notebook workspace.
-   Clicking a dataset calls the backend for a validated loading
    snippet.
-   The frontend uses the JupyterLab integration to insert a new code
    cell into the active notebook.
-   The cell is inserted at the current cursor/selected position or at
    the end according to a documented UI rule.
-   The cell is not executed automatically.
-   The student clicks Run.
-   The kernel reads the local read-only dataset path.

Example:

``` python
import pandas as pd

df = pd.read_csv("/opt/opencs/datasets/iris/v1/iris.csv")
df.head()
```

For Parquet:

``` python
import pandas as pd

df = pd.read_parquet("/opt/opencs/datasets/nyc-taxi-sample/v1/trips.parquet")
df.head()
```

**Implementation decision:** Use a supported JupyterLab extension/plugin
or a supported JupyterLab frontend integration to insert notebook cells.
Do not depend on fragile DOM selectors or private internal JupyterLab
APIs. Pin and test the JupyterLab extension version against the selected
JupyterLab image.

If the catalogue is outside JupyterLab, the OpenCS frontend must
communicate with the active notebook through a supported
integration/extension and the authenticated Jupyter server context. Do
not expose a reusable JupyterHub API token to browser JavaScript.

### 10.7 Dataset access security

-   Dataset source volume is mounted read-only.
-   Student pods cannot modify canonical dataset files.
-   Backend returns only published dataset IDs and safe relative paths.
-   Reject path traversal (`../`) and arbitrary path input.
-   Dataset catalogue metadata is not treated as executable code.
-   Validate dataset file type, size, checksum and provenance before
    publication.

------------------------------------------------------------------------

## 11. Standard Python Environment and Kernel Consistency

### 11.1 Immutable image strategy

Build one centrally maintained image for the course release:

``` text
registry.example.edu/opencs/analytics:1.0.0
registry.example.edu/opencs/analytics:1.1.0
```

In production, deploy by immutable image digest, not only a mutable tag.

The image contains: - Supported Python version. - JupyterLab. - IPython
and ipykernel. - Pinned data-analysis and ML libraries. - Required
system libraries. - Standard non-root user configuration. -
Health/readiness configuration. - Optional approved JupyterLab
extensions.

### 11.2 Version control

-   Pin Python and all Python package versions.
-   Use a lock file generated and checked in source control.
-   Build images through CI.
-   Run import tests for every required library.
-   Run notebook smoke tests against representative datasets.
-   Record image tag and digest.
-   Publish a release manifest.
-   Roll out image changes centrally.
-   Keep a previous known-good image for rollback.

### 11.3 Example environment validation

``` python
import sys
import numpy
import pandas
import matplotlib
import seaborn
import scipy
import sklearn
import xgboost

print(sys.version)
print("NumPy:", numpy.__version__)
print("Pandas:", pandas.__version__)
print("Scikit-learn:", sklearn.__version__)
print("XGBoost:", xgboost.__version__)
```

A student should not be able to silently mutate the shared base image.
If custom package installation is ever introduced, it must use a
separate controlled environment/profile rather than changing the
course's standard image.

### 11.4 Kernel consistency vs reproducibility

Same image gives consistent starting dependencies, but not necessarily
identical results for every program. Random seeds, CPU architecture,
library nondeterminism and dataset version can affect results.

For reproducible course exercises: - Pin image digest. - Pin dataset
version/checksum. - Set random seeds in examples where appropriate. -
Record exercise/template version. - Avoid promising bit-for-bit
identical ML results unless specifically tested.

------------------------------------------------------------------------

## 12. 400-User Compute Architecture and Capacity Planning

### 12.1 User workload model

For the initial release:

-   One active student session maps to one single-user Jupyter server
    pod.
-   Each pod has one student's Jupyter server and one or more kernels.
-   Kubernetes schedules pods across worker nodes.
-   Pods receive resource requests and limits.
-   Persistent home storage is separate from ephemeral compute.
-   Idle servers are shut down after a configured interval.

### 12.2 Initial resource profiles

These are proposed starting profiles. Benchmark real lessons and
exercises before making them default.

  -----------------------------------------------------------------------------
  Profile     CPU request    CPU limit       Memory Memory limit Use
                                            request              
  ---------- ------------ ------------ ------------ ------------ --------------
  Standard           500m        1 CPU        1 GiB        2 GiB Introductory
                                                                 analytics

  Medium            1 CPU        2 CPU        2 GiB        4 GiB Larger EDA/ML
                                                                 tasks

  Heavy             2 CPU        4 CPU        4 GiB        8 GiB Approved
                                                                 intensive
                                                                 tasks
  -----------------------------------------------------------------------------

Do not grant the Heavy profile to all users by default.

### 12.3 Illustrative capacity arithmetic

If all 400 concurrent users are on Standard and the pod limit is 1 vCPU
/ 2 GiB:

-   Aggregate CPU limit: 400 vCPU.
-   Aggregate memory limit: 800 GiB.
-   Add capacity for system services, JupyterHub, ingress, monitoring,
    storage services and scheduling headroom.
-   Capacity planning must also account for CPU requests, not just
    limits.

An illustrative 20% planning allowance would imply approximately 480
vCPU and 960 GiB of memory-equivalent planning capacity for the user
workload plus headroom. This is not a procurement specification or a
guarantee. Kubernetes requests, actual utilization, node allocatable
capacity, system overhead and workload distribution must be measured
before final sizing.

### 12.4 Scheduling and admission control

-   Use Kubernetes requests/limits and namespace ResourceQuota.
-   Apply LimitRange defaults.
-   Apply per-user pod limits and storage quotas.
-   Use node labels/taints only where workload classes require them.
-   Keep control-plane components away from student workload saturation
    where possible.
-   Set a maximum number of active sessions.
-   When capacity is exhausted, show a clear "capacity full / retry" or
    queue state.
-   Avoid uncontrolled retry loops.
-   Do not promise that Kubernetes Cluster Autoscaler can instantly add
    capacity; node provisioning and image pulls take time.

### 12.5 Idle shutdown

-   Configure JupyterHub idle culling.
-   Define idle as no meaningful user activity according to tested
    policy.
-   Warn the student before shutdown if appropriate.
-   Save notebook files before the server is stopped.
-   Do not assume all in-memory variables can be saved.
-   Allow users to relaunch the same environment later.

### 12.6 Distributed computing clarification

There are two different meanings of distributing computation:

**Required in v1 --- distribute independent student sessions:**
Kubernetes spreads 400 separate student notebook pods across multiple
worker nodes. This is the main concurrency/scaling requirement.

**Optional later --- distribute one student's computation:** Dask or Ray
can distribute one student's large dataframe/model workload across
multiple workers. This needs additional resource isolation, worker
lifecycle, networking, quotas and cost controls. It is not necessary to
deliver the initial product.

Do not add a Dask/Ray cluster per student in v1 unless the course
explicitly requires it.

### 12.7 Load test plan

Test at staged concurrency levels:

-   1 user: correctness baseline.
-   25 users: early concurrency test.
-   100 users: medium load.
-   200 users: high load.
-   400 users: target load.
-   400 users with mixed workloads: realistic target.
-   Burst launch test: many users launch notebooks within a short
    window.
-   Recovery test: terminate a worker node/pod during activity.

Measure: - Launch success rate. - Time from click to ready notebook. -
p50/p95/p99 startup latency. - Kernel execution latency. - CPU and
memory utilization. - Pod pending time and scheduling failures. - Image
pull time. - Persistent volume attach/mount latency. - Dataset read
throughput and cache hit rate. - API and database latency. - Error rates
and recovery time.

A load test must execute representative operations, not merely create
idle pods.

------------------------------------------------------------------------

## 13. Security and Isolation

Student notebooks execute arbitrary Python. Treat notebook code as
untrusted code execution.

### 13.1 Minimum controls

-   Authenticate every user.
-   Enforce authorization on every backend operation.
-   One notebook pod per active student.
-   Run containers as non-root.
-   Disallow privileged containers.
-   Drop unnecessary Linux capabilities.
-   Use seccomp and AppArmor/SELinux profiles where supported.
-   Set CPU, memory, PID and ephemeral-storage limits.
-   Do not mount host root or Docker/container runtime sockets.
-   Do not expose Kubernetes service-account credentials to student
    pods.
-   Disable unnecessary service-account token mounting.
-   Use Kubernetes NetworkPolicies.
-   Restrict egress to approved destinations where feasible.
-   Mount shared datasets read-only.
-   Use per-student persistent storage and access control.
-   Keep secrets out of images and notebooks.
-   Use TLS for browser and service communication.
-   Rate-limit sensitive APIs.
-   Audit administrative actions.

### 13.2 Stronger sandboxing

Standard containers share the host kernel. For a platform executing
untrusted student code, evaluate gVisor or Kata Containers as an
additional isolation boundary. Test compatibility and overhead before
selecting one.

Do not claim that ordinary Docker containers provide VM-equivalent
isolation.

### 13.3 Network policy

Default-deny student pod network access where practical, then allow only
necessary traffic: - JupyterHub proxy/control paths. - DNS. - Approved
dataset/object storage path if required. - Required platform
endpoints. - Explicitly approved external learning resources, if
allowed.

Students should not be able to access PostgreSQL, Kubernetes
control-plane endpoints, other student pods or internal administrative
services.

### 13.4 Secrets

-   Store credentials in Kubernetes Secrets or an approved secret
    manager.
-   Never bake credentials into Docker images.
-   Never return JupyterHub API tokens to frontend JavaScript.
-   Use service-to-service credentials with least privilege.
-   Rotate credentials and audit access.

------------------------------------------------------------------------

## 14. Application APIs

The API is a modular FastAPI application. Exact routes can be finalized
during implementation, but the contracts below establish ownership and
expected behaviour.

### 14.1 Authentication / profile

  Method   Endpoint                   Purpose
  -------- -------------------------- -------------------------------------
  GET      `/api/v1/me`               Current authenticated user and role
  GET      `/api/v1/me/preferences`   User preferences
  PATCH    `/api/v1/me/preferences`   Update allowed preferences

Authentication should normally be delegated to the institution's
OIDC/LDAP provider and/or JupyterHub-compatible authenticator. Do not
invent a separate password store if campus identity is available.

### 14.2 Learning

  -------------------------------------------------------------------------------------------------
  Method                  Endpoint                                          Purpose
  ----------------------- ------------------------------------------------- -----------------------
  GET                     `/api/v1/learning/paths`                          List published learning
                                                                            paths

  GET                     `/api/v1/learning/modules`                        List modules

  GET                     `/api/v1/learning/lessons/{lesson_id}`            Get lesson content

  POST                    `/api/v1/learning/lessons/{lesson_id}/progress`   Update lesson progress

  POST                    `/api/v1/learning/lessons/{lesson_id}/launch`     Create/retrieve
                                                                            notebook activity
                                                                            launch information
  -------------------------------------------------------------------------------------------------

### 14.3 Practice

  -----------------------------------------------------------------------------------------------------
  Method                  Endpoint                                              Purpose
  ----------------------- ----------------------------------------------------- -----------------------
  GET                     `/api/v1/practice/exercises`                          Search/filter exercises

  GET                     `/api/v1/practice/exercises/{exercise_id}`            Exercise details

  POST                    `/api/v1/practice/exercises/{exercise_id}/attempts`   Create attempt and
                                                                                starter notebook

  GET                     `/api/v1/practice/attempts/{attempt_id}`              Get own attempt status

  POST                    `/api/v1/practice/attempts/{attempt_id}/evaluate`     Request permitted
                                                                                evaluation

  GET                     `/api/v1/practice/attempts/{attempt_id}/feedback`     Retrieve feedback
  -----------------------------------------------------------------------------------------------------

### 14.4 Dataset catalogue

  ------------------------------------------------------------------------------------------
  Method                  Endpoint                                   Purpose
  ----------------------- ------------------------------------------ -----------------------
  GET                     `/api/v1/datasets`                         Search/list published
                                                                     datasets

  GET                     `/api/v1/datasets/{dataset_id}`            Dataset details

  GET                     `/api/v1/datasets/{dataset_id}/preview`    Bounded sample preview

  GET                     `/api/v1/datasets/{dataset_id}/snippet`    Get validated loading
                                                                     code

  GET                     `/api/v1/datasets/{dataset_id}/versions`   List permitted versions
  ------------------------------------------------------------------------------------------

The snippet endpoint returns code and metadata. It does not execute
code.

Example response:

``` json
{
  "dataset_id": "iris",
  "version": "1",
  "language": "python",
  "cell_type": "code",
  "auto_execute": false,
  "code": "import pandas as pd\n\ndf = pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv')\ndf.head()"
}
```

### 14.5 Notebook launch and management

  ----------------------------------------------------------------------------------------
  Method                  Endpoint                                 Purpose
  ----------------------- ---------------------------------------- -----------------------
  GET                     `/api/v1/notebooks/server`               Get current user's
                                                                   server state

  POST                    `/api/v1/notebooks/server/start`         Request server start

  POST                    `/api/v1/notebooks/server/stop`          Request server stop

  GET                     `/api/v1/notebooks`                      List own notebook
                                                                   metadata

  POST                    `/api/v1/notebooks`                      Create notebook
                                                                   metadata/template

  PATCH                   `/api/v1/notebooks/{notebook_id}`        Rename/update metadata

  DELETE                  `/api/v1/notebooks/{notebook_id}`        Delete owned notebook

  GET                     `/api/v1/notebooks/{notebook_id}/open`   Resolve authorized
                                                                   notebook open
                                                                   destination
  ----------------------------------------------------------------------------------------

JupyterHub remains authoritative for the actual notebook server
lifecycle. FastAPI must not independently create or manage Kubernetes
pods.

### 14.6 API rules

-   Require authentication.
-   Verify ownership and role on every resource operation.
-   Validate IDs and payloads.
-   Apply pagination to catalogue/list endpoints.
-   Rate-limit launch and evaluation requests.
-   Use idempotency keys for operations that could be retried.
-   Return structured error codes.
-   Do not return filesystem paths that expose other users' storage.
-   Do not expose internal service credentials.

------------------------------------------------------------------------

## 15. Data Model

PostgreSQL stores platform metadata. Notebook files and dataset binaries
live in storage systems, not in relational table blobs.

### 15.1 Core entities

``` mermaid
erDiagram
    USER ||--o{ ENROLLMENT : has
    COURSE ||--o{ ENROLLMENT : contains
    COURSE ||--o{ LEARNING_PATH : offers
    LEARNING_PATH ||--o{ MODULE : contains
    MODULE ||--o{ LESSON : contains
    USER ||--o{ LESSON_PROGRESS : tracks
    LESSON ||--o{ LESSON_PROGRESS : records
    USER ||--o{ NOTEBOOK : owns
    USER ||--o{ PRACTICE_ATTEMPT : makes
    EXERCISE ||--o{ PRACTICE_ATTEMPT : receives
    DATASET ||--o{ DATASET_VERSION : has
    DATASET ||--o{ EXERCISE : supports
    LESSON }o--o{ DATASET : references
    EXERCISE }o--o{ DATASET : references
```

### 15.2 Suggested tables

#### `users`

-   `id` UUID primary key.
-   `external_subject` unique identity-provider subject.
-   `email`.
-   `display_name`.
-   `role`.
-   `created_at`.
-   `is_active`.

#### `courses`

-   `id` UUID.
-   `name`.
-   `code`.
-   `term`.
-   `status`.
-   `created_at`.

#### `enrollments`

-   `id` UUID.
-   `course_id`.
-   `user_id`.
-   `role_in_course`.
-   `created_at`.

Unique constraint: `(course_id, user_id)`.

#### `learning_paths`

-   `id`.
-   `title`.
-   `description`.
-   `published_version`.
-   `is_published`.

#### `modules`

-   `id`.
-   `learning_path_id`.
-   `title`.
-   `position`.
-   `is_published`.

#### `lessons`

-   `id`.
-   `module_id`.
-   `title`.
-   `content_json` or versioned content reference.
-   `position`.
-   `is_published`.
-   `version`.

#### `lesson_progress`

-   `id`.
-   `user_id`.
-   `lesson_id`.
-   `status`.
-   `completed_at`.
-   `updated_at`.

Unique constraint: `(user_id, lesson_id)`.

#### `datasets`

-   `id`.
-   `slug`.
-   `title`.
-   `description`.
-   `category`.
-   `is_published`.
-   `created_at`.

#### `dataset_versions`

-   `id`.
-   `dataset_id`.
-   `version`.
-   `object_key`.
-   `relative_mount_path`.
-   `format`.
-   `size_bytes`.
-   `sha256`.
-   `license`.
-   `source_url` or provenance text.
-   `schema_json`.
-   `published_at`.

Unique constraint: `(dataset_id, version)`.

#### `exercises`

-   `id`.
-   `slug`.
-   `title`.
-   `topic`.
-   `difficulty`.
-   `instructions_json`.
-   `starter_notebook_object_key`.
-   `evaluation_config`.
-   `version`.
-   `is_published`.

#### `practice_attempts`

-   `id`.
-   `user_id`.
-   `exercise_id`.
-   `notebook_reference`.
-   `status`.
-   `score` nullable.
-   `feedback_json`.
-   `started_at`.
-   `submitted_at`.

#### `notebooks`

-   `id`.
-   `user_id`.
-   `title`.
-   `storage_key` or controlled home-relative reference.
-   `environment_image_digest`.
-   `created_at`.
-   `updated_at`.

Do not use a browser-supplied arbitrary `storage_key` to access a
notebook. Resolve storage through the authenticated owner.

### 15.3 Indexing

At minimum: - Unique index on `users.external_subject`. - Index on
`enrollments(course_id, user_id)`. - Index on
`lessons(module_id, position)`. - Index on
`lesson_progress(user_id, lesson_id)`. - Index on
`datasets(is_published, category)`. - Index on
`dataset_versions(dataset_id, version)`. - Index on
`exercises(topic, difficulty, is_published)`. - Index on
`practice_attempts(user_id, exercise_id, started_at)`. - Index on
`notebooks(user_id, updated_at)`.

Use migrations (e.g. Alembic) and keep schema changes
version-controlled.

------------------------------------------------------------------------

## 16. Deployment Architecture

### 16.1 Recommended stack

  -----------------------------------------------------------------------
  Layer                   Selected technology     Purpose
  ----------------------- ----------------------- -----------------------
  Frontend                React + TypeScript      Student/instructor UI

  UI/data visualization   Appropriate React       Lesson and catalogue
                          chart/table libraries   visuals

  Backend                 FastAPI                 Modular application
                                                  APIs

  API schema              OpenAPI                 Documented contracts

  Database                PostgreSQL              Durable metadata

  Cache                   Redis (optional)        Cache/rate
                                                  limits/short-lived
                                                  coordination

  Notebook management     JupyterHub              Multi-user notebook
                                                  lifecycle

  Spawner                 KubeSpawner             Kubernetes user pods

  Notebook UI             JupyterLab              Editing and execution

  Orchestration           Kubernetes              Multi-node scheduling

  Image build             Docker/BuildKit         Standard environment
                                                  image

  Image registry          Harbor or institutional Private image storage
                          registry                

  Object storage          MinIO                   Dataset/content objects
                                                  and backups

  Persistent homes        CSI-backed per-user     Notebook persistence
                          volumes or supported    
                          shared filesystem       

  Dataset serving         Read-only shared        Fast local dataset
                          volume/node cache       access

  Ingress                 NGINX Ingress or        HTTPS and routing
                          supported equivalent    

  Metrics                 Prometheus              Metrics collection

  Dashboards              Grafana                 Monitoring

  Logs                    Loki or institutional   Centralized logs
                          log stack               

  Packaging               Helm                    Reproducible deployment

  CI/CD                   Institutional Git/CI    Tests and releases
                          platform                
  -----------------------------------------------------------------------

### 16.2 JupyterHub deployment

Use the Zero to JupyterHub Helm chart as the baseline deployment model,
with: - Hub. - Configurable HTTP Proxy. - KubeSpawner. - Single-user
notebook image. - Persistent user storage. - Authenticator
integration. - Idle culling. - Resource profiles. - Pod security
configuration.

Pin chart versions and test upgrades in staging before production.

### 16.3 Kubernetes node groups

Conceptual node groups:

1.  **Control/system nodes:** Kubernetes system services and essential
    platform control-plane workloads, depending on cluster distribution.
2.  **Platform nodes:** FastAPI, frontend, JupyterHub, ingress and
    supporting services.
3.  **Notebook worker nodes:** Student Jupyter pods.
4.  **Storage/observability nodes:** Only if the chosen storage and
    monitoring design requires dedicated nodes.

The exact grouping depends on whether the cluster is managed or
self-hosted. Do not assume a particular cloud provider.

### 16.4 Autoscaling

-   Horizontal Pod Autoscaler can scale stateless application replicas
    based on measured metrics.
-   Cluster Autoscaler or the platform's node autoscaler can add worker
    nodes where infrastructure supports it.
-   Notebook pod creation is driven by JupyterHub/KubeSpawner.
-   Autoscaling is not instantaneous; maintain baseline capacity for
    scheduled lab peaks.
-   Use admission control to avoid launching more sessions than the
    cluster can serve.

### 16.5 Storage selection details

-   Student homes: one persistent volume per student, provisioned
    through CSI or a supported shared filesystem.
-   Dataset source: MinIO as canonical store.
-   Dataset runtime access: read-only node cache or shared read-only
    filesystem.
-   Backups: scheduled versioned backups to a separate protected
    destination.
-   Test restore, not just backup creation.

For 600 possible users, provision storage based on per-user quota and
retention policy. Do not create unlimited storage.

------------------------------------------------------------------------

## 17. Reliability and Failure Handling

  -----------------------------------------------------------------------
  Failure                             Expected response
  ----------------------------------- -----------------------------------
  Student kernel crashes              Student restarts kernel; saved
                                      notebook remains

  Student notebook pod crashes        JupyterHub/Kubernetes restarts or
                                      student relaunches; persistent home
                                      remains

  Worker node fails                   Kubernetes reschedules eligible
                                      pods; unsaved in-memory state may
                                      be lost

  FastAPI instance fails              Another replica serves requests;
                                      database remains source of truth

  PostgreSQL unavailable              Metadata operations fail safely; no
                                      false success

  MinIO unavailable                   Existing cached/local data may
                                      continue to work; new object
                                      operations fail/retry safely

  Dataset cache unavailable           Fall back to approved source if
                                      designed, or show temporary dataset
                                      unavailability

  Container registry unavailable      Cached images may start; uncached
                                      image pulls fail until registry
                                      recovers

  Cluster at capacity                 Queue or reject launches with clear
                                      retry guidance

  Persistent volume unavailable       Do not silently create an empty
                                      replacement home; alert and
                                      recover/reattach

  Proxy unavailable                   Notebook access temporarily
                                      unavailable; recover proxy and
                                      preserve backend sessions where
                                      possible
  -----------------------------------------------------------------------

### 17.1 Recovery rules

-   Notebook persistence must be tested through pod deletion and
    recreation.
-   Use PostgreSQL backups and point-in-time recovery where available.
-   Back up MinIO buckets and version critical objects.
-   Keep infrastructure configuration in version control.
-   Keep known-good image versions.
-   Document recovery steps and test them periodically.
-   Alert on storage capacity, pending pods, repeated restarts and
    failed volume mounts.

------------------------------------------------------------------------

## 18. Observability

### 18.1 Metrics

**Platform** - API request count, latency and error rate. - PostgreSQL
connections and query latency. - Redis health if used. - Authentication
failures.

**JupyterHub** - Active user servers. - Server start success/failure. -
Server startup duration. - Spawn pending duration. - Idle server
count. - Proxy errors.

**Kubernetes** - Node CPU/memory. - Pod CPU/memory. - Pending pods. -
OOM kills. - Restarts. - Scheduling failures. - PVC attach/mount
failures. - Namespace quota utilization.

**Storage** - MinIO availability and latency. - Dataset cache
hit/miss. - Dataset read throughput. - Persistent volume utilization and
IOPS where available.

**Practice** - Exercise launches. - Attempt counts. - Evaluation latency
and errors. - Completion rates.

### 18.2 Dashboards

Create: - OpenCS Platform Overview. - JupyterHub Session Health. -
Kubernetes Cluster Capacity. - Notebook Startup Performance. - Dataset
Storage and Cache. - Practice Evaluation Health.

Avoid logging notebook source code, secrets or sensitive student data by
default.

------------------------------------------------------------------------

## 19. Testing Strategy

### 19.1 Unit tests

-   Dataset metadata validation.
-   Dataset snippet generation.
-   API authorization and ownership checks.
-   Lesson/practice content validation.
-   Notebook metadata operations.
-   Resource profile configuration.

### 19.2 Integration tests

-   Login → notebook launch.
-   New notebook → save → stop server → relaunch → reopen.
-   Previous notebook list returns only the current user's notebooks.
-   Dataset click inserts the correct cell.
-   Inserted cell does not auto-execute.
-   Run cell successfully reads the selected dataset.
-   Read-only dataset files cannot be modified.
-   Lesson "Open in Notebook" launches the correct starter content.
-   Practice attempt creates a private starter notebook.
-   Evaluation runs in the intended isolated environment.

### 19.3 Environment tests

For every image release: - Python version check. - Import test for every
required library. - JupyterLab starts. - Kernel starts and executes a
simple cell. - CSV and Parquet sample reads work. -
Matplotlib/Seaborn/Plotly examples render. - scikit-learn Random Forest
example works. - XGBoost smoke test works. - Notebook save/reopen works.

### 19.4 Security tests

-   Student A cannot read Student B's notebook.
-   Student A cannot access Student B's pod.
-   Student cannot modify shared datasets.
-   Student pod cannot access Kubernetes API credentials.
-   Student cannot reach PostgreSQL/admin endpoints directly.
-   Path traversal is rejected.
-   Hidden practice tests are not exposed.
-   Resource limits stop runaway processes.

### 19.5 Load tests

Use a realistic mix of: - Simultaneous login. - Notebook server
launch. - Notebook open/save. - Dataset catalogue search. - Dataset
reads. - Pandas transformations. - Plot generation. - Small scikit-learn
model training. - Idle shutdown and relaunch.

Report the actual hardware, image digest, workload mix, concurrency,
duration, latency percentiles and error rate. A test that only launches
empty pods is not sufficient proof of 400-user compute capacity.

------------------------------------------------------------------------

## 20. Repository and Code Organization

A suggested implementation repository:

``` text
opencs-labs/
├── README.md
├── HLD.md
├── docs/
│   ├── ADR/
│   │   ├── 001-jupyterhub-kubernetes.md
│   │   ├── 002-dataset-storage.md
│   │   ├── 003-notebook-persistence.md
│   │   └── 004-environment-versioning.md
│   ├── API.md
│   ├── SECURITY.md
│   ├── OPERATIONS.md
│   └── LOAD_TEST_PLAN.md
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── features/
│   │   │   ├── learning/
│   │   │   ├── practice/
│   │   │   ├── notebooks/
│   │   │   └── datasets/
│   │   ├── components/
│   │   └── services/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── courses/
│   │   ├── learning/
│   │   ├── practice/
│   │   ├── datasets/
│   │   ├── notebooks/
│   │   ├── db/
│   │   └── schemas/
│   ├── migrations/
│   └── tests/
├── notebook-image/
│   ├── Dockerfile
│   ├── requirements.in
│   ├── requirements.lock
│   └── smoke-tests/
├── jupyterlab-extension/
│   ├── package.json
│   └── src/
├── content/
│   ├── lessons/
│   ├── exercises/
│   └── starter-notebooks/
├── datasets/
│   ├── manifests/
│   └── README.md
├── infrastructure/
│   ├── helm/
│   ├── kubernetes/
│   ├── storage/
│   ├── monitoring/
│   └── policies/
├── scripts/
│   ├── validate_datasets.py
│   ├── build_notebook_image.sh
│   └── seed_content.py
└── tests/
    ├── integration/
    ├── security/
    └── load/
```

This is a target structure. The implementation agent should adapt it to
an existing repository rather than destructively replacing existing
code.

------------------------------------------------------------------------

## 21. Implementation Roadmap

Build in vertical slices so that the core user journey works early.

### Phase 0 --- Architecture and decisions

-   Confirm hosting model: on-premises, cloud or hybrid.
-   Confirm identity provider.
-   Confirm Kubernetes distribution and storage CSI.
-   Record architecture decisions (ADRs).
-   Define the 400-user workload assumptions.

### Phase 1 --- Notebook foundation

-   Deploy Kubernetes development cluster.
-   Deploy JupyterHub with KubeSpawner.
-   Build the standard Python notebook image.
-   Configure per-user storage.
-   Validate two users cannot access each other's files or kernels.

**Exit condition:** Two independent users can create, run, save and
reopen notebooks in isolated environments.

### Phase 2 --- OpenCS application shell

-   Build React navigation: Learn, Practice, Notebook Workspace.
-   Build FastAPI modular backend.
-   Configure authentication and role checks.
-   Add PostgreSQL migrations.
-   Integrate notebook launch/status.

**Exit condition:** Authenticated students can launch their own notebook
from the application.

### Phase 3 --- Dataset catalogue

-   Add MinIO dataset bucket and manifests.
-   Publish initial verified datasets.
-   Build catalogue search/details/preview.
-   Build JupyterLab cell insertion integration.
-   Test that click inserts but does not execute.
-   Test that running the cell reads the correct local dataset.

**Exit condition:** Dataset-to-notebook workflow works end to end.

### Phase 4 --- Learning experience

-   Build topic/module/lesson structure.
-   Create reusable lesson components.
-   Add worked examples and visual explanations.
-   Link lessons to datasets and notebook activities.
-   Add progress tracking.

**Exit condition:** A student can learn a topic and continue it in a
real notebook.

### Phase 5 --- Practice experience

-   Build exercise catalogue and details.
-   Add starter notebook templates.
-   Add hints and difficulty.
-   Add isolated evaluation for deterministic exercises.
-   Store attempts and feedback.

**Exit condition:** A student can practice a topic in a private notebook
and receive valid feedback.

### Phase 6 --- Production controls

-   Add resource profiles, quotas and idle culling.
-   Add monitoring and alerts.
-   Add backups and restore tests.
-   Add network/security policies.
-   Test failure scenarios.

### Phase 7 --- Scale validation

-   Run staged concurrency tests.
-   Run 400-user mixed-workload test.
-   Tune worker node count and storage.
-   Validate burst launch and recovery.
-   Publish a capacity report with measured evidence.

------------------------------------------------------------------------

## 22. Acceptance Criteria

The project is not complete merely because the homepage looks good.
These end-to-end criteria define the minimum successful product.

### Core workflow

-   [ ] Student can authenticate.
-   [ ] Student can create a new notebook.
-   [ ] Student can see and reopen previous notebooks.
-   [ ] Notebook files persist across server restart.
-   [ ] Student can search and inspect datasets.
-   [ ] Clicking a dataset inserts a code cell into the active notebook.
-   [ ] The inserted cell is not automatically executed.
-   [ ] Running the cell loads the correct centrally stored dataset.
-   [ ] Shared original datasets are read-only.

### Teaching

-   [ ] Student can browse structured learning paths.
-   [ ] Lessons include objectives, explanation, examples and visual
    support.
-   [ ] Lessons link to relevant datasets and notebook activities.
-   [ ] Lesson activities execute in the standard notebook environment.
-   [ ] Progress is persisted.

### Practice

-   [ ] Student can browse topic/difficulty-based exercises.
-   [ ] Exercise includes instructions, dataset and starter notebook.
-   [ ] Student can practice in their own isolated notebook.
-   [ ] Hints and feedback work.
-   [ ] Hidden tests/solutions are not exposed.
-   [ ] Practice progress is persisted.

### Environment

-   [ ] Required libraries import successfully.
-   [ ] Python/Jupyter versions are pinned.
-   [ ] All student sessions use an approved image digest.
-   [ ] Image release has smoke-test evidence.
-   [ ] Randomly installing/upgrading packages cannot mutate the shared
    base image.

### Multi-user and security

-   [ ] Two users have isolated kernels and storage.
-   [ ] Students cannot access each other's notebooks.
-   [ ] Resource limits are enforced.
-   [ ] Idle shutdown and relaunch work.
-   [ ] Capacity exhaustion is handled gracefully.
-   [ ] 400 concurrent representative sessions pass the agreed load
    test.
-   [ ] Failure and restore procedures are tested.

------------------------------------------------------------------------

## 23. Architecture Decisions and Alternatives

### ADR-001: JupyterHub rather than a custom notebook manager

**Decision:** Use JupyterHub.

**Reason:** JupyterHub already provides multi-user server lifecycle,
authentication integration, proxy routing and spawner abstractions.

**Rejected:** Implementing custom notebook server management in FastAPI.

### ADR-002: Kubernetes + KubeSpawner

**Decision:** Use Kubernetes and KubeSpawner for the target
400-concurrent-user deployment.

**Reason:** Independent notebook pods can be scheduled across multiple
nodes with resource controls and lifecycle management.

**Trade-off:** Operational complexity; requires a properly managed
cluster and storage.

### ADR-003: One standardized immutable notebook image

**Decision:** Use one versioned Python analytics image per approved
course release/profile.

**Reason:** Consistent package versions and reproducible lessons.

**Rejected:** Installing packages independently every time a student
launches a notebook.

### ADR-004: MinIO plus persistent notebook volumes

**Decision:** Use MinIO for canonical datasets/content objects and a
proper persistent volume solution for student homes.

**Reason:** Object storage is suitable for versioned datasets and
backups; notebook home directories need reliable filesystem semantics.

**Rejected:** Treating object storage as a drop-in POSIX home filesystem
without a tested integration.

### ADR-005: Dataset cell insertion, not auto-execution

**Decision:** Clicking a dataset inserts a code cell; the student runs
it.

**Reason:** Student retains control and can inspect/learn from the code.

**Rejected:** Automatically executing code when a dataset is clicked.

### ADR-006: Modular monolith for platform APIs

**Decision:** Keep learning, practice, dataset and notebook
orchestration modules inside one well-structured FastAPI backend
initially.

**Reason:** Easier development and deployment without losing module
boundaries.

**Rejected:** Prematurely creating many microservices.

### ADR-007: Distribute independent sessions first

**Decision:** Kubernetes distributes student notebook pods across nodes.
Dask/Ray is deferred.

**Reason:** The primary requirement is concurrent independent student
sessions, not distributed execution within every student's individual
notebook.

### ADR-008: JupyterLab extension for dataset insertion

**Decision:** Use a supported, version-pinned JupyterLab
integration/extension to insert cells into the active notebook.

**Reason:** Correctly targets the notebook model and avoids brittle
browser DOM manipulation.

**Rejected:** Clicking a dataset and merely copying code to an unrelated
text box, or relying on unsupported internal JupyterLab APIs.

------------------------------------------------------------------------

## 24. Risks and Open Decisions

These decisions must be finalized before production deployment.

  -----------------------------------------------------------------------
  Open decision           Why it matters          Required resolution
  ----------------------- ----------------------- -----------------------
  On-premises vs cloud vs Determines node         Select deployment
  hybrid                  provisioning,           environment
                          networking, cost and    
                          operations              

  Identity provider       Determines login/auth   Confirm campus
                          integration             OIDC/LDAP availability

  Kubernetes distribution Affects installation    Select managed or
                          and upgrades            self-managed Kubernetes

  Persistent volume       Determines notebook     Validate CSI/shared
  backend                 durability and          filesystem
                          performance             

  Dataset serving         Affects 400-user read   Benchmark node cache vs
  mechanism               performance             shared filesystem

  Dataset licenses        Redistribution may be   Verify each source and
                          restricted              license

  External internet from  Security and package    Define network policy
  kernels                 access                  

  Idle timeout            Balances cost and       Agree course policy
                          student experience      

  Practice grading model  Arbitrary analysis is   Define deterministic
                          difficult to grade      checks/rubrics
                          objectively             

  Actual node capacity    Cannot be inferred from Benchmark
                          concurrency count alone representative workload

  JupyterLab extension    Needed for cell         Pin/test extension and
  compatibility           insertion               JupyterLab versions
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 25. Instructions for Implementation Agents

This HLD is the architectural source of truth. Any implementation agent
(Command Code, Aider or another coding assistant) must follow these
rules:

1.  Read this entire `HLD.md` before editing code.
2.  Inspect the existing repository, environment and running services
    before making changes.
3.  Produce a concise implementation plan and identify conflicts with
    the existing code.
4.  Preserve working features; do not rewrite the project unnecessarily.
5.  Implement the actual end-to-end student workflow, not only mock
    screens.
6.  Use JupyterHub/KubeSpawner for notebook lifecycle; do not implement
    a parallel custom kernel manager.
7.  Never execute student code in the FastAPI process.
8.  Implement dataset selection as **insert code cell, do not
    auto-run**.
9.  Ensure the inserted cell runs inside the authenticated student's own
    kernel.
10. Keep canonical datasets read-only and centrally versioned.
11. Pin environment dependencies and test every required library.
12. Separate persistent notebook files from ephemeral kernel state.
13. Enforce per-user storage and compute isolation.
14. Do not hardcode secrets, credentials, tokens or machine-specific
    paths.
15. Do not invent successful load-test results or claim 400-user
    readiness without evidence.
16. Add automated tests for every acceptance criterion that can be
    tested.
17. Document commands, environment variables, deployment steps and
    recovery procedures.
18. Record deviations from this HLD in an Architecture Decision Record
    (ADR) and explain the trade-off.
19. Use real API and JupyterHub integration; do not leave core actions
    as frontend-only mock interactions.
20. Finish with a report containing implemented features, changed files,
    tests run, test results, known limitations and next steps.

### Definition of done

A working vertical slice must demonstrate:

**Login → Learn a concept → Open a lesson notebook → Browse datasets →
Click dataset → Insert code cell → Run cell → Analyze/visualize data →
Open Practice → Complete an exercise → Save notebook → Reopen previous
notebook.**

The platform must then demonstrate isolated sessions for multiple
students and provide measured evidence for the 400-concurrent-user
target.

------------------------------------------------------------------------

## 26. Final Product Statement

**OpenCS Labs is an interactive Data Analysis and Data Science learning
platform built around real Jupyter notebook execution. It teaches
students through guided, visual, step-by-step lessons; provides a
dedicated hands-on practice environment; and gives every student a
persistent, isolated and consistent Python notebook workspace with a
centrally managed local dataset library and a complete data-science
ecosystem. Kubernetes and JupyterHub distribute and manage independent
student workloads so the platform can be engineered and tested for up to
400 concurrent notebook users in a class of 600.**

This statement, the scope, the architecture decisions and the acceptance
criteria above define the intended product.
