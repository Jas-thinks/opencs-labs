"""Smoke tests for the pinned OpenCS analytics notebook image.

These run *inside* the built image, so they verify the thing students actually
get rather than a developer machine:

    docker run --rm \
        -v "$PWD/../datasets/serving:/opt/opencs/datasets:ro" \
        -v "$PWD/smoke-tests:/smoke:ro" \
        opencs/analytics:1.0.0 python -m pytest /smoke -q

Every library listed in ``requirements.lock`` is imported and used for one
trivial operation. The point is to catch a broken wheel, a missing system
library (xgboost needs ``libgomp1``), or an ABI mismatch between numpy and a
compiled dependency -- failures that only appear at import or first call time.

Kept deliberately tiny and fast: a few dozen rows, a two-round boosted model, no
network access.
"""

from __future__ import annotations

import os
import tempfile

import pytest


# --------------------------------------------------------------------------- #
# Environment contract
# --------------------------------------------------------------------------- #
def test_matplotlib_backend_is_headless():
    """Student notebooks run without a display; Agg is what makes plt.show() safe."""
    backend = os.environ.get("MPLBACKEND")
    assert backend in (None, "Agg"), f"MPLBACKEND must be unset or 'Agg', got {backend!r}"


def test_python_does_not_write_bytecode():
    """Pods mount the notebook home read-write but stay lean; no .pyc litter."""
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"


def test_dataset_mount_point_exists():
    """The read-only dataset tree is mounted here by KubeSpawner at spawn time."""
    assert os.path.isdir("/opt/opencs/datasets"), "/opt/opencs/datasets is not a directory"


def test_grade_runner_is_present():
    """The grading sandbox runs this exact path inside the image."""
    assert os.path.isfile("/opt/opencs/grade_runner.py"), "/opt/opencs/grade_runner.py is missing"


def test_work_directory_is_writable():
    """JupyterHub starts the single-user server with cwd=/home/opencs/work."""
    assert os.access("/home/opencs/work", os.W_OK), "/home/opencs/work is not writable"


# --------------------------------------------------------------------------- #
# numpy / pandas
# --------------------------------------------------------------------------- #
def test_numpy_array_mean():
    import numpy as np

    values = np.array([1.0, 2.0, 3.0, 4.0])
    assert values.shape == (4,)
    assert values.mean() == pytest.approx(2.5)
    assert values.dtype == np.float64


def test_pandas_dataframe_roundtrip():
    import pandas as pd

    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    assert list(frame.columns) == ["a", "b"]
    assert frame["a"].sum() == 6
    # groupby is the operation most likely to hit a compiled-extension problem
    grouped = frame.groupby("b", observed=True)["a"].sum()
    assert grouped.loc["x"] == 1


def test_pandas_reads_csv(tmp_path):
    import pandas as pd

    path = tmp_path / "tiny.csv"
    path.write_text("n,label\n1,a\n2,b\n", encoding="utf-8")
    frame = pd.read_csv(path)
    assert frame.shape == (2, 2)
    assert frame["n"].tolist() == [1, 2]


# --------------------------------------------------------------------------- #
# matplotlib / seaborn
# --------------------------------------------------------------------------- #
def test_matplotlib_saves_png_with_agg():
    import matplotlib

    # Explicitly pin Agg: the test must pass even when run outside the image.
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(2, 2))
    try:
        axes.plot([0, 1, 2], [0, 1, 4])
        axes.set_title("smoke")
        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            figure.savefig(handle.name, format="png")
            handle.seek(0)
            head = handle.read(8)
    finally:
        plt.close(figure)
    assert head == b"\x89PNG\r\n\x1a\n", "savefig did not produce a PNG"


def test_seaborn_plot_on_a_dataframe():
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 4, 9, 16]})
    figure, axes = plt.subplots(figsize=(2, 2))
    try:
        sns.scatterplot(data=frame, x="x", y="y", ax=axes)
    finally:
        plt.close(figure)


# --------------------------------------------------------------------------- #
# plotly
# --------------------------------------------------------------------------- #
def test_plotly_imports():
    """Import only: rendering needs a browser and is covered by JupyterLab itself."""
    import plotly
    import plotly.express as px

    assert plotly.__version__
    figure = px.scatter(x=[1, 2, 3], y=[3, 2, 1])
    assert len(figure.data) == 1


# --------------------------------------------------------------------------- #
# scipy / statsmodels
# --------------------------------------------------------------------------- #
def test_scipy_normal_distribution():
    from scipy import stats

    normal = stats.norm(loc=0.0, scale=1.0)
    assert normal.mean() == pytest.approx(0.0)
    assert normal.cdf(0.0) == pytest.approx(0.5)
    assert stats.norm.sf(0.0) == pytest.approx(0.5)


def test_statsmodels_ols():
    import numpy as np
    import statsmodels.api as sm

    x = np.arange(10.0)
    y = 2.0 * x + 1.0
    model = sm.OLS(y, sm.add_constant(x)).fit()
    assert model.params[0] == pytest.approx(1.0, abs=1e-8)
    assert model.params[1] == pytest.approx(2.0, abs=1e-8)


# --------------------------------------------------------------------------- #
# scikit-learn / xgboost
# --------------------------------------------------------------------------- #
def test_sklearn_linear_regression():
    import numpy as np
    from sklearn.linear_model import LinearRegression

    x = np.arange(20.0).reshape(-1, 1)
    y = 3.0 * x.ravel() + 2.0
    model = LinearRegression().fit(x, y)
    assert model.coef_[0] == pytest.approx(3.0, abs=1e-8)
    assert model.intercept_ == pytest.approx(2.0, abs=1e-8)


def test_xgboost_classifier_fits():
    """xgboost links against libgomp, so a fit is the real system-library check."""
    import numpy as np
    from xgboost import XGBClassifier

    rng = np.random.default_rng(seed=0)
    features = rng.normal(size=(40, 3))
    labels = (features[:, 0] + features[:, 1] > 0).astype(int)

    model = XGBClassifier(
        n_estimators=2,
        max_depth=2,
        learning_rate=0.5,
        n_jobs=1,
        tree_method="hist",
        verbosity=0,
    )
    model.fit(features, labels)
    predictions = model.predict(features)
    assert predictions.shape == (40,)
    assert set(predictions.tolist()) <= {0, 1}


# --------------------------------------------------------------------------- #
# Tabular IO and SQL
# --------------------------------------------------------------------------- #
def test_openpyxl_roundtrip(tmp_path):
    from openpyxl import Workbook, load_workbook

    path = tmp_path / "tiny.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["n", "label"])
    sheet.append([1, "a"])
    workbook.save(path)

    reloaded = load_workbook(path, read_only=True)
    rows = list(reloaded.active.iter_rows(values_only=True))
    reloaded.close()
    assert rows[0] == ("n", "label")
    assert rows[1] == (1, "a")


def test_pyarrow_roundtrip(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"n": [1, 2, 3], "label": ["a", "b", "c"]})
    path = tmp_path / "tiny.parquet"
    pq.write_table(table, path)
    reloaded = pq.read_table(path)
    assert reloaded.num_rows == 3
    assert reloaded.column("n").to_pylist() == [1, 2, 3]


def test_fastparquet_roundtrip(tmp_path):
    """Exercise fastparquet directly.

    pandas deprecates its ``engine="fastparquet"`` dispatch, so routing through
    pandas would test a code path that is on its way out. The library itself is
    what the image promises, so this uses its own reader and writer.
    """
    import pandas as pd
    from fastparquet import ParquetFile, write

    path = tmp_path / "tiny-fast.parquet"
    write(str(path), pd.DataFrame({"n": [1, 2, 3]}), compression="UNCOMPRESSED")

    table = ParquetFile(str(path)).to_pandas()
    assert table["n"].tolist() == [1, 2, 3]


def test_sqlalchemy_sqlite_in_memory():
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE t (n INTEGER)"))
            connection.execute(text("INSERT INTO t (n) VALUES (7)"))
            value = connection.execute(text("SELECT n FROM t")).scalar_one()
        assert value == 7
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# Jupyter stack
# --------------------------------------------------------------------------- #
def test_jupyterlab_and_kernelspec_are_registered():
    """JupyterHub starts this server; a missing kernelspec means no kernel at all."""
    import jupyterlab
    import jupyter_client.kernelspec

    assert jupyterlab.__version__
    specs = jupyter_client.kernelspec.KernelSpecManager().find_kernel_specs()
    assert "python3" in specs, f"python3 kernelspec is not registered: {sorted(specs)}"


def test_ipykernel_is_importable():
    import ipykernel

    assert ipykernel.__version__


def test_jupyterhub_singleuser_entrypoint_is_present():
    """The Hub needs this binary inside the notebook image.

    JupyterHub proxies /user/<name>/ to this server and validates the token it
    minted for the user. If `jupyterhub-singleuser` is absent the Hub cannot
    authenticate that token, so every write to the notebook returns 403 or 500.
    This has to live in the *single-user* image, not only in the Hub image.
    """
    import shutil

    import jupyterhub

    assert jupyterhub.__version__
    binary = shutil.which("jupyterhub-singleuser")
    assert binary, "jupyterhub-singleuser is not on PATH in the notebook image"
