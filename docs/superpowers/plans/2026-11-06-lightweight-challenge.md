# Lightweight Challenge Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Replace the active heavy full-stack challenge with a broken web app whose installed app and test dependencies stay below 100 MB, with dependencies already present in the IDE image.

**Architecture:** Use the Flask project's official tutorial blog as the challenge source. Keep its pristine upstream checkout, copy only the tutorial into a separate broken repository, and preinstall pinned Flask and pytest packages into the code-server image. The IDE mounts only the broken copy.

**Tech Stack:** Python, Flask, SQLite, HTML/CSS, pytest, Docker, code-server.

**Source:** `pallets/flask` tag `3.1.2`, commit `2c1b30d0503cfb064f1cb252e6614a06915a362a`, BSD-3-Clause.

## Tasks

- [x] Copy the tutorial into `broken-repos/broken-flaskr-blog`, retain its license, document the intended repair, and initialize a clean challenge Git baseline (`0ddde74`).
- [x] Introduce an authorization bug in post updates and deletes; pristine source passes 24 tests, broken challenge fails the ownership test.
- [x] Add Python and pinned Flask/pytest dependencies to the code-server image; installed virtual environment measures 32 MB.
- [x] Point Compose at only the new broken repo, rebuild, and verify the IDE, tests, and workspace mount.
