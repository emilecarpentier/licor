import duckdb

from licor.ingestion import LmuTelemetryDatabase


def test_reads_lmu_duckdb_metadata_and_fixed_channels(tmp_path):
    db_path = tmp_path / "sample.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("create table metadata(key varchar primary key, value varchar)")
    con.execute(
        """
        insert into metadata values
        ('TrackName', 'Circuit de Spa-Francorchamps'),
        ('CarClass', 'LMP2_ELMS')
        """
    )
    con.execute(
        """
        create table channelsList(
            channelName varchar primary key,
            frequency integer,
            unit varchar
        )
        """
    )
    con.execute("insert into channelsList values ('Fuel Level', 20, 'L')")
    con.execute("create table eventsList(eventName varchar primary key, unit varchar)")
    con.execute("insert into eventsList values ('Lap', '')")
    con.execute("create table \"Lap\"(ts double, value usmallint)")
    con.execute("insert into \"Lap\" values (100.0, 0), (130.0, 1), (250.5, 2)")
    con.execute("create table \"Fuel Level\"(value float)")
    con.execute("insert into \"Fuel Level\" values (45.0), (44.9), (44.8)")
    con.close()

    with LmuTelemetryDatabase(db_path) as telemetry:
        assert telemetry.metadata()["TrackName"] == "Circuit de Spa-Francorchamps"
        assert telemetry.channels()["Fuel Level"].frequency_hz == 20
        assert telemetry.events()["Lap"].name == "Lap"
        assert telemetry.session_start_ts() == 100.0

        fuel = telemetry.fixed_channel("Fuel Level")
        assert fuel.columns == ["sample_index", "ts", "elapsed_s", "value"]
        assert fuel["sample_index"].to_list() == [0, 1, 2]
        assert fuel["ts"].to_list() == [100.0, 100.05, 100.1]

        laps = telemetry.lap_intervals()
        assert len(laps) == 2
        assert laps[0].lap_number == 0
        assert laps[0].duration_s == 30.0
        assert laps[1].lap_number == 1
        assert laps[1].duration_s == 120.5
