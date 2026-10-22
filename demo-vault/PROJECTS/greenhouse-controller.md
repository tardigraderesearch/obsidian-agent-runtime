---
tags: [electronics, garden]
status: active
---
# Greenhouse Controller

A small microcontroller that reads soil moisture and switches a watering pump.

## Status

As of 2026-03-09: pump relay works (after adding a level shifter), probe A
calibrated, probe B calibration in progress.

## Hardware

- Microcontroller board with 3.3 V logic.
- Two capacitive soil-moisture probes (A and B). Background in
  [[REFERENCE/soil-moisture-sensors]].
- 5 V relay board with a level shifter on the signal line.
- 12 V diaphragm pump.

## Sub-notes

- [[PROJECTS/greenhouse-controller/sensor-calibration]]
- [[PROJECTS/greenhouse-controller/watering-schedule]]

## Decisions

- Capacitive probes, not resistive. See [[REFERENCE/decisions-log]].
