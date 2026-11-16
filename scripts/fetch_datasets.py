#!/usr/bin/env python3
"""Download, normalise, checksum and manifest the OpenCS dataset library.

Every value written into a manifest is derived from the actual file on disk
or from the recorded, verified source. Nothing is guessed.

Usage:
    python scripts/fetch_datasets.py [--force] [--only iris,titanic]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "datasets" / "raw"
SERVING = REPO / "datasets" / "serving"
MANIFESTS = REPO / "datasets" / "manifests"
USER_AGENT = "OpenCS-Labs-DatasetBuilder/1.0 (+educational use)"
SAMPLE_ROWS = 20000
PREVIEW_ROWS = 5


@dataclass
class DatasetSpec:
    slug: str
    title: str
    category: str
    summary: str
    description: str
    teaching_tags: list[str]
    position: int
    license: str
    license_url: str
    license_status: str
    source_url: str
    attribution: str
    builder: Callable[[], tuple[pd.DataFrame, str, str, dict[str, Any]]]
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def download(url: str, target: Path, force: bool = False) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return target
    print(f"  downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value


def preview_records(frame: pd.DataFrame, rows: int = PREVIEW_ROWS) -> list[dict[str, Any]]:
    sample = frame.head(rows).astype(object)
    records = []
    for record in sample.to_dict(orient="records"):
        records.append({key: json_safe(value) for key, value in record.items()})
    return records


def column_schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [{"name": str(name), "dtype": str(dtype)} for name, dtype in frame.dtypes.items()]


# ---------------------------------------------------------------------------
# builders — each returns (dataframe, format, file name, transform metadata)
# ---------------------------------------------------------------------------


def build_iris() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    archive = download(
        "https://archive.ics.uci.edu/static/public/53/iris.zip", RAW / "iris" / "iris.zip"
    )
    extract = RAW / "iris" / "extracted"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    frame = pd.read_csv(
        extract / "iris.data",
        names=["sepal_length", "sepal_width", "petal_length", "petal_width", "species"],
    )
    frame = frame.dropna(how="all")
    frame["species"] = frame["species"].str.replace("Iris-", "", regex=False)
    return frame, "csv", "iris.csv", {"rows": len(frame), "source_rows": 150, "sampled": False}


def build_titanic() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/titanic.csv",
        RAW / "titanic" / "titanic.csv",
    )
    frame = pd.read_csv(path)
    return frame, "csv", "titanic.csv", {"rows": len(frame), "source_rows": len(frame), "sampled": False}


def build_wine_quality() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    archive = download(
        "https://archive.ics.uci.edu/static/public/186/wine+quality.zip",
        RAW / "wine-quality" / "wine+quality.zip",
    )
    extract = RAW / "wine-quality" / "extracted"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    frame = pd.read_csv(extract / "winequality-red.csv", sep=";")
    frame.columns = [column.strip().lower().replace(" ", "_") for column in frame.columns]
    return frame, "csv", "winequality-red.csv", {
        "rows": len(frame),
        "source_rows": len(frame),
        "sampled": False,
        "subset": "red wine only",
    }


def build_california_housing() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://raw.githubusercontent.com/ageron/handson-ml2/master/datasets/housing/housing.csv",
        RAW / "california-housing" / "housing.csv",
    )
    frame = pd.read_csv(path)
    return frame, "csv", "housing.csv", {"rows": len(frame), "source_rows": len(frame), "sampled": False}


def build_penguins() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv",
        RAW / "palmer-penguins" / "penguins.csv",
    )
    frame = pd.read_csv(path)
    return frame, "csv", "penguins.csv", {"rows": len(frame), "source_rows": len(frame), "sampled": False}


def build_diabetes() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    from sklearn.datasets import load_diabetes

    data = load_diabetes(as_frame=True)
    frame = data.frame.copy()
    frame = frame.rename(columns={"target": "disease_progression"})
    return frame, "csv", "diabetes.csv", {
        "rows": len(frame),
        "source_rows": len(frame),
        "sampled": False,
        "subset": "scikit-learn bundled dataset; features are pre-scaled",
    }


def build_tips() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv",
        RAW / "tips" / "tips.csv",
    )
    frame = pd.read_csv(path)
    return frame, "csv", "tips.csv", {"rows": len(frame), "source_rows": len(frame), "sampled": False}


def build_gapminder() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv",
        RAW / "gapminder" / "gapminderDataFiveYear.csv",
    )
    frame = pd.read_csv(path)
    frame = frame.rename(
        columns={
            "lifeExp": "life_exp",
            "gdpPercap": "gdp_per_cap",
        }
    )
    frame.columns = [column.lower() for column in frame.columns]
    return frame, "csv", "gapminder.csv", {"rows": len(frame), "source_rows": len(frame), "sampled": False}


def build_nyc_taxi() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    path = download(
        "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet",
        RAW / "nyc-taxi-sample" / "yellow_tripdata_2024-01.parquet",
    )
    columns = [
        "tpep_pickup_datetime",
        "tpep_dropoff_datetime",
        "passenger_count",
        "trip_distance",
        "PULocationID",
        "DOLocationID",
        "fare_amount",
        "tip_amount",
        "total_amount",
        "payment_type",
    ]
    frame = pd.read_parquet(path, columns=columns)
    total = len(frame)
    frame = frame.sample(n=SAMPLE_ROWS, random_state=42).sort_index().reset_index(drop=True)
    frame = frame.rename(columns={"PULocationID": "pu_location_id", "DOLocationID": "do_location_id"})
    return frame, "parquet", "trips.parquet", {
        "rows": len(frame),
        "source_rows": total,
        "sampled": True,
        "sample_method": f"pandas DataFrame.sample(n={SAMPLE_ROWS}, random_state=42)",
        "subset": "selected 10 teaching columns from the January 2024 yellow taxi trip file",
    }


def build_retail_sales() -> tuple[pd.DataFrame, str, str, dict[str, Any]]:
    archive = download(
        "https://archive.ics.uci.edu/static/public/352/online+retail.zip",
        RAW / "retail-sales" / "online+retail.zip",
    )
    extract = RAW / "retail-sales" / "extracted"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    workbook = next(extract.glob("*.xlsx"))
    frame = pd.read_excel(workbook, engine="openpyxl")
    frame.columns = [
        "invoice_no",
        "stock_code",
        "description",
        "quantity",
        "invoice_date",
        "unit_price",
        "customer_id",
        "country",
    ]
    total = len(frame)
    frame = frame.dropna(subset=["invoice_no", "stock_code"]).reset_index(drop=True)
    frame = frame.sample(n=min(SAMPLE_ROWS, len(frame)), random_state=42).sort_index().reset_index(drop=True)
    frame["invoice_date"] = pd.to_datetime(frame["invoice_date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame, "csv", "online-retail-sample.csv", {
        "rows": len(frame),
        "source_rows": total,
        "sampled": True,
        "sample_method": f"pandas DataFrame.sample(n={SAMPLE_ROWS}, random_state=42)",
        "subset": "Online Retail transactions sample",
    }


SPECS: list[DatasetSpec] = [
    DatasetSpec(
        slug="iris",
        title="Iris",
        category="Classic classification",
        summary="150 flower measurements across three iris species — the canonical first dataset.",
        description=(
            "Four numeric measurements (sepal length/width, petal length/width) for 150 irises "
            "from three species: setosa, versicolor and virginica. Ideal for first contact with "
            "tables, descriptive statistics, grouping, histograms, scatter plots and classification."
        ),
        teaching_tags=["EDA", "visualization", "classification", "groupby"],
        position=10,
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_status="verified",
        source_url="https://archive.ics.uci.edu/dataset/53/iris",
        attribution="R. A. Fisher (1936), distributed by the UCI Machine Learning Repository.",
        builder=build_iris,
    ),
    DatasetSpec(
        slug="titanic",
        title="Titanic",
        category="Data cleaning",
        summary="891 passengers with missing ages, cabins and ports — built for cleaning practice.",
        description=(
            "Passenger-level records from the RMS Titanic. Contains genuine missing values "
            "(age, cabin, embarked), categorical columns and a binary survival outcome. "
            "Used throughout the Data Cleaning and Introduction to ML modules."
        ),
        teaching_tags=["missing values", "cleaning", "classification", "EDA"],
        position=20,
        license="Not stated by source (seaborn-data mirror)",
        license_url="https://github.com/mwaskom/seaborn-data",
        license_status="review-required",
        source_url="https://raw.githubusercontent.com/mwaskom/seaborn-data/master/titanic.csv",
        attribution="Original compilers: Vanderbilt University Department of Biostatistics; mirrored in seaborn-data.",
        builder=build_titanic,
        notes="Source repository does not publish an explicit license. Confirm redistribution terms before production use.",
    ),
    DatasetSpec(
        slug="wine-quality",
        title="Wine Quality (Red)",
        category="Statistics",
        summary="1,599 red wines with 11 physicochemical measurements and a quality score.",
        description=(
            "Physicochemical tests (acidity, sugar, sulphates, alcohol, pH) alongside a sensory "
            "quality score from 0–10. A natural fit for correlation, distributions, hypothesis "
            "testing and both regression and classification."
        ),
        teaching_tags=["statistics", "correlation", "regression", "classification"],
        position=30,
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_status="verified",
        source_url="https://archive.ics.uci.edu/dataset/186/wine+quality",
        attribution="P. Cortez et al. (2009), UCI Machine Learning Repository.",
        builder=build_wine_quality,
        notes="The red wine table only; the white wine table is not included in v1.",
    ),
    DatasetSpec(
        slug="california-housing",
        title="California Housing",
        category="Regression",
        summary="20,640 districts with median house values — the classic regression workload.",
        description=(
            "One row per census block group: location, housing age, rooms, bedrooms, population, "
            "households, median income, ocean proximity and median house value. Used for "
            "feature analysis, regression and evaluation."
        ),
        teaching_tags=["regression", "feature analysis", "EDA", "geography"],
        position=40,
        license="Public domain (StatLib)",
        license_url="https://www.dcc.fc.up.pt/~ltorgo/Regression/cal_housing.html",
        license_status="review-required",
        source_url="https://raw.githubusercontent.com/ageron/handson-ml2/master/datasets/housing/housing.csv",
        attribution="Pace & Barry (1997), StatLib; CSV mirror maintained by Aurélien Géron (Apache-2.0 repository).",
        builder=build_california_housing,
        notes="Data originates from StatLib. The mirror repository is Apache-2.0; confirm data redistribution terms.",
    ),
    DatasetSpec(
        slug="palmer-penguins",
        title="Palmer Penguins",
        category="Visualization",
        summary="344 penguins from three islands with bill, flipper and mass measurements.",
        description=(
            "A modern replacement for Iris with real missing values and three species across "
            "three islands. Excellent for distributions, box plots, scatter plots, "
            "group comparison and classification."
        ),
        teaching_tags=["visualization", "EDA", "classification", "missing values"],
        position=50,
        license="CC0 1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        license_status="verified",
        source_url="https://github.com/allisonhorst/palmerpenguins",
        attribution="Horst, Hill & Gorman (2020), palmerpenguins.",
        builder=build_penguins,
    ),
    DatasetSpec(
        slug="diabetes",
        title="Diabetes Progression",
        category="Regression",
        summary="442 patients, ten baseline variables and a one-year disease progression target.",
        description=(
            "Ten baseline predictors (age, sex, BMI, blood pressure and six serum measurements) "
            "with a quantitative measure of disease progression one year later. Used for "
            "regression, feature importance and model evaluation."
        ),
        teaching_tags=["regression", "evaluation", "feature importance"],
        position=60,
        license="BSD-3-Clause (scikit-learn bundled data)",
        license_url="https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset",
        license_status="review-required",
        source_url="https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset",
        attribution="Bundled with scikit-learn; original data from the diabetes study distributed with the package.",
        builder=build_diabetes,
        notes="Features are already mean-centred and scaled by scikit-learn. Do not re-scale blindly in lessons.",
    ),
    DatasetSpec(
        slug="tips",
        title="Restaurant Tips",
        category="GroupBy",
        summary="244 restaurant bills with tip, day, time and party size.",
        description=(
            "A small, readable table for learning groupby, aggregation and categorical "
            "visualization: total bill, tip, sex, smoker, day, time and party size."
        ),
        teaching_tags=["groupby", "aggregation", "visualization"],
        position=70,
        license="Not stated by source (seaborn-data mirror)",
        license_url="https://github.com/mwaskom/seaborn-data",
        license_status="review-required",
        source_url="https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv",
        attribution="Bryant & Smith, mirrored in seaborn-data.",
        builder=build_tips,
        notes="Source repository does not publish an explicit license. Confirm redistribution terms before production use.",
    ),
    DatasetSpec(
        slug="gapminder",
        title="Gapminder",
        category="Time series",
        summary="Life expectancy, population and GDP per capita by country, 1952–2007.",
        description=(
            "Country-year observations every five years with life expectancy, population and "
            "GDP per capita, grouped by continent. Used for time comparisons, joins of "
            "concepts and multi-series line charts."
        ),
        teaching_tags=["time series", "visualization", "aggregation", "countries"],
        position=80,
        license="MIT",
        license_url="https://github.com/plotly/datasets/blob/master/LICENSE",
        license_status="verified",
        source_url="https://github.com/plotly/datasets",
        attribution="Gapminder Foundation data, distributed in the plotly/datasets repository.",
        builder=build_gapminder,
    ),
    DatasetSpec(
        slug="nyc-taxi-sample",
        title="NYC Taxi Sample",
        category="Large data",
        summary="20,000 yellow-taxi trips from January 2024 in Parquet format.",
        description=(
            "A deterministic 20,000-row sample of New York yellow-taxi trips: pickup and "
            "dropoff times, distance, fare, tip and payment type. Delivered as Parquet to "
            "teach columnar file formats and aggregation on a larger table."
        ),
        teaching_tags=["parquet", "aggregation", "datetime", "business analytics"],
        position=90,
        license="NYC Open Data Terms of Use",
        license_url="https://opendata.cityofnewyork.us/overview/#termsofuse",
        license_status="verified",
        source_url="https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
        attribution="New York City Taxi & Limousine Commission Trip Record Data.",
        builder=build_nyc_taxi,
    ),
    DatasetSpec(
        slug="retail-sales",
        title="Online Retail Sales",
        category="Business analytics",
        summary="20,000 real retail invoice lines with products, quantities and countries.",
        description=(
            "A deterministic sample of UK online-retail invoices: stock codes, descriptions, "
            "quantities, unit prices, customers and countries. Used for business aggregation, "
            "revenue analysis and customer grouping."
        ),
        teaching_tags=["groupby", "business analytics", "aggregation", "datetime"],
        position=100,
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_status="verified",
        source_url="https://archive.ics.uci.edu/dataset/352/online+retail",
        attribution="Daqing Chen et al. (2012), UCI Machine Learning Repository.",
        builder=build_retail_sales,
    ),
]


def write_dataset(spec: DatasetSpec, force: bool) -> dict[str, Any]:
    print(f"[{spec.slug}] building")
    frame, fmt, file_name, transform = spec.builder()
    version_dir = SERVING / spec.slug / "v1"
    if version_dir.exists() and not force:
        manifest_path = MANIFESTS / f"{spec.slug}.json"
        if manifest_path.exists():
            print(f"[{spec.slug}] already present (use --force to rebuild)")
            return json.loads(manifest_path.read_text())
    version_dir.mkdir(parents=True, exist_ok=True)
    target = version_dir / file_name
    if fmt == "csv":
        frame.to_csv(target, index=False)
    elif fmt == "parquet":
        frame.to_parquet(target, index=False)
    else:  # pragma: no cover - defensive
        raise ValueError(f"unsupported format {fmt}")

    checksum = sha256_file(target)
    size = target.stat().st_size
    relative = f"{spec.slug}/v1/{file_name}"

    version_doc = {
        "version": 1,
        "format": fmt,
        "file": file_name,
        "object_key": relative,
        "relative_mount_path": relative,
        "sha256": checksum,
        "size_bytes": size,
        "row_count": int(len(frame)),
        "columns": column_schema(frame),
        "preview": preview_records(frame),
        "published_at": dt.datetime.now(dt.UTC).isoformat(),
        "transform": transform,
    }

    manifest = {
        "schema_version": 1,
        "dataset_id": spec.slug,
        "slug": spec.slug,
        "title": spec.title,
        "category": spec.category,
        "summary": spec.summary,
        "description": spec.description,
        "teaching_tags": spec.teaching_tags,
        "position": spec.position,
        "license": spec.license,
        "license_url": spec.license_url,
        "license_status": spec.license_status,
        "source_url": spec.source_url,
        "attribution": spec.attribution,
        "notes": spec.notes,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "generator": "scripts/fetch_datasets.py",
        "versions": [version_doc],
        **spec.extra,
    }

    MANIFESTS.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFESTS / f"{spec.slug}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (version_dir / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": spec.slug,
                "version": 1,
                "title": spec.title,
                "file": file_name,
                "sha256": checksum,
                "size_bytes": size,
                "row_count": int(len(frame)),
                "license": spec.license,
                "source_url": spec.source_url,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"[{spec.slug}] wrote {relative} ({size:,} bytes, sha256 {checksum[:12]}…)")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild datasets that already exist")
    parser.add_argument("--only", default="", help="comma separated dataset slugs")
    args = parser.parse_args()

    selected = {slug.strip() for slug in args.only.split(",") if slug.strip()}
    specs = [spec for spec in SPECS if not selected or spec.slug in selected]
    if selected:
        unknown = selected - {spec.slug for spec in specs}
        if unknown:
            print(f"unknown datasets: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    RAW.mkdir(parents=True, exist_ok=True)
    SERVING.mkdir(parents=True, exist_ok=True)
    failures = 0
    for spec in specs:
        try:
            write_dataset(spec, args.force)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"[{spec.slug}] FAILED: {exc}", file=sys.stderr)

    # Write a catalogue index so the UI/backend can be checked without the DB.
    index = []
    for path in sorted(MANIFESTS.glob("*.json")):
        doc = json.loads(path.read_text())
        index.append(
            {
                "slug": doc["slug"],
                "title": doc["title"],
                "category": doc["category"],
                "license_status": doc["license_status"],
                "version": doc["versions"][0]["version"],
                "sha256": doc["versions"][0]["sha256"],
                "row_count": doc["versions"][0]["row_count"],
            }
        )
    (MANIFESTS / "index.json").write_text(json.dumps(index, indent=2) + "\n")

    print(f"\n{len(specs) - failures}/{len(specs)} datasets built")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
