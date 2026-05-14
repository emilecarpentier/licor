# LMU Channels Observed In DuckDB Telemetry

This file documents the channel and event inventory observed in the first LMU
DuckDB telemetry sample. It should be updated if future files add, remove, or
rename signals.

The expected channel/event inventory is also stored as JSON in
`config/lmu_telemetry_config.reference.json`. The JSON file contains the native
LMU names and channel frequencies. This Markdown file adds human-readable units
observed from DuckDB `channelsList` and `eventsList`.

## Fixed-Frequency Channels

| Channel | Frequency | Unit |
| --- | ---: | --- |
| Ambient Temperature | 1 Hz | C |
| Brake Pos | 50 Hz | % |
| Brake Pos Unfiltered | 50 Hz | % |
| Brake Thickness | 10 Hz | % |
| Brakes Air Temp | 50 Hz | C |
| Brakes Force | 50 Hz | % |
| Brakes Temp | 50 Hz | C |
| Clutch Pos | 50 Hz | % |
| Clutch Pos Unfiltered | 50 Hz | % |
| Clutch RPM | 100 Hz | RPM |
| Engine Oil Temp | 7 Hz | C |
| Engine RPM | 100 Hz | RPM |
| Engine Water Temp | 7 Hz | C |
| FFB Output | 100 Hz | % |
| Front3rdDeflection | 100 Hz | m |
| FrontRideHeight | 100 Hz | m |
| Fuel Level | 20 Hz | L |
| G Force Lat | 10 Hz | G |
| G Force Long | 10 Hz | G |
| G Force Vert | 10 Hz | G |
| GPS Latitude | 10 Hz | deg |
| GPS Longitude | 10 Hz | deg |
| GPS Speed | 10 Hz | m/s |
| GPS Time | 100 Hz | s |
| Ground Speed | 100 Hz | km/h |
| Lap Dist | 10 Hz | m |
| OverheatingState | 2 Hz |  |
| Path Lateral | 10 Hz | m |
| Rear3rdDeflection | 100 Hz | m |
| RearRideHeight | 100 Hz | m |
| Regen Rate | 100 Hz | kW |
| RideHeights | 100 Hz | m |
| SoC | 20 Hz | % |
| Steering Pos | 100 Hz | % |
| Steering Pos Unfiltered | 100 Hz | % |
| Steering Shaft Torque | 100 Hz | Nm |
| SurfaceTypes | 5 Hz |  |
| Susp Pos | 100 Hz | m |
| TC | 100 Hz |  |
| Throttle Pos | 50 Hz | % |
| Throttle Pos Unfiltered | 50 Hz | % |
| Time Behind Next | 2 Hz | s |
| Total Dist | 10 Hz | m |
| Track Edge | 10 Hz | m |
| Track Temperature | 1 Hz | C |
| Turbo Boost Pressure | 100 Hz | Pa |
| Tyres Wear | 10 Hz | % |
| TyresCarcassTemp | 5 Hz | C |
| TyresPressure | 10 Hz | kPa |
| TyresRimTemp | 50 Hz | C |
| TyresRubberTemp | 10 Hz | C |
| TyresTempCentre | 100 Hz | C |
| TyresTempLeft | 100 Hz | C |
| TyresTempRight | 100 Hz | C |
| Virtual Energy | 20 Hz | % |
| Wheel Speed | 100 Hz | m/s |
| Wind Heading | 1 Hz | deg |
| Wind Speed | 1 Hz | m/s |

## Event Signals

| Event | Unit |
| --- | --- |
| ABS |  |
| ABSLevel |  |
| AntiStall Activated |  |
| Best LapTime | s |
| Best Sector1 | s |
| Best Sector2 | s |
| Brake Bias Rear |  |
| Brake Migration |  |
| CloudDarkness | % |
| Current LapTime | s |
| Current Sector |  |
| Current Sector1 | s |
| Current Sector2 | s |
| Engine Max RPM | RPM |
| Finish Status |  |
| FrontFlapActivated |  |
| FuelMixtureMap |  |
| Gear |  |
| Headlights State | On/Off |
| In Pits |  |
| Lap |  |
| Lap Time | s |
| Last Sector1 | s |
| Last Sector2 | s |
| LastImpactMagnitude |  |
| LaunchControlActive |  |
| Minimum Path Wetness | % |
| OffpathWetness | % |
| RearFlapActivated |  |
| RearFlapLegalStatus |  |
| Sector1 Flag |  |
| Sector2 Flag |  |
| Sector3 Flag |  |
| Speed Limiter |  |
| TCCut |  |
| TCLevel |  |
| TCSlipAngle |  |
| TyresCompound |  |
| WheelsDetached |  |
| Yellow Flag State |  |

## Notes For LICOR

- `Gear` is event-style in the observed file, not a fixed-frequency channel.
- `Ground Speed` is in km/h while `GPS Speed` is in m/s.
- `Fuel Level` is sampled at 20 Hz, which is enough for lap-level fuel usage.
- `Lap Dist` is sampled at 10 Hz, so distance-based zone boundaries should be
  treated as approximate until resampled/aligned.
- Brake and throttle are sampled at 50 Hz, which is sufficient for initial LICO
  detection.
