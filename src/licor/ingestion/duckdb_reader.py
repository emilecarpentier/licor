from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import polars as pl


@dataclass(frozen=True)
class ChannelInfo:
    name: str
    frequency_hz: int
    unit: str


@dataclass(frozen=True)
class EventInfo:
    name: str
    unit: str


@dataclass(frozen=True)
class LapInterval:
    lap_number: int
    start_ts: float
    end_ts: float
    duration_s: float


class LmuTelemetryDatabase:
    """Read a Le Mans Ultimate telemetry DuckDB file."""

    def __init__(self, path: str | Path, *, read_only: bool = True) -> None:
        self.path = Path(path)
        self._connection = duckdb.connect(str(self.path), read_only=read_only)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> LmuTelemetryDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._connection

    def table_names(self) -> list[str]:
        rows = self.connection.execute("show tables").fetchall()
        return [str(row[0]) for row in rows]

    def metadata(self) -> dict[str, str]:
        rows = self.connection.execute(
            "select key, value from metadata order by key"
        ).fetchall()
        return {str(key): str(value) for key, value in rows}

    def channels(self) -> dict[str, ChannelInfo]:
        rows = self.connection.execute(
            """
            select channelName, frequency, unit
            from channelsList
            order by channelName
            """
        ).fetchall()
        return {
            str(name): ChannelInfo(str(name), int(frequency), str(unit))
            for name, frequency, unit in rows
        }

    def events(self) -> dict[str, EventInfo]:
        rows = self.connection.execute(
            """
            select eventName, unit
            from eventsList
            order by eventName
            """
        ).fetchall()
        return {str(name): EventInfo(str(name), str(unit)) for name, unit in rows}

    def table_schema(self, table_name: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            f"pragma table_info({quote_identifier(table_name)})"
        ).fetchall()
        return [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "primary_key": bool(row[5]),
            }
            for row in rows
        ]

    def session_start_ts(self) -> float:
        if "Lap" in self.table_names():
            row = self.connection.execute('select min(ts) from "Lap"').fetchone()
            if row is not None and row[0] is not None:
                return float(row[0])

        event_tables = [
            name
            for name in self.events()
            if "ts" in {column["name"] for column in self.table_schema(name)}
        ]
        if not event_tables:
            return 0.0

        min_values = []
        for table_name in event_tables:
            row = self.connection.execute(
                f"select min(ts) from {quote_identifier(table_name)}"
            ).fetchone()
            if row is not None and row[0] is not None:
                min_values.append(float(row[0]))
        return min(min_values, default=0.0)

    def fixed_channel(self, channel_name: str, *, start_ts: float | None = None) -> pl.DataFrame:
        channel = self.channels()[channel_name]
        table = quote_identifier(channel_name)
        value_columns = [column["name"] for column in self.table_schema(channel_name)]
        start = self.session_start_ts() if start_ts is None else start_ts
        column_sql = ", ".join(quote_identifier(column) for column in value_columns)
        rows = self.connection.execute(
            f"""
            select
                sample_index,
                ? + sample_index / ? as ts,
                sample_index / ? as elapsed_s,
                {column_sql}
            from (
                select row_number() over () - 1 as sample_index, *
                from {table}
            )
            order by sample_index
            """,
            [start, channel.frequency_hz, channel.frequency_hz],
        ).fetchall()
        columns = ["sample_index", "ts", "elapsed_s", *value_columns]
        return pl.DataFrame(rows, schema=columns, orient="row")

    def event_series(self, event_name: str) -> pl.DataFrame:
        rows = self.connection.execute(
            f"select * from {quote_identifier(event_name)} order by ts"
        ).fetchall()
        columns = [column["name"] for column in self.table_schema(event_name)]
        frame = pl.DataFrame(rows, schema=columns, orient="row")
        if "ts" in frame.columns:
            frame = frame.with_columns(
                (pl.col("ts") - self.session_start_ts()).alias("elapsed_s")
            )
        return frame

    def lap_intervals(self) -> list[LapInterval]:
        rows = self.connection.execute(
            'select ts, value from "Lap" order by ts'
        ).fetchall()
        intervals: list[LapInterval] = []
        for (start_ts, lap_number), (end_ts, _) in zip(rows, rows[1:]):
            intervals.append(
                LapInterval(
                    lap_number=int(lap_number),
                    start_ts=float(start_ts),
                    end_ts=float(end_ts),
                    duration_s=float(end_ts) - float(start_ts),
                )
            )
        return intervals


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
