#!/usr/bin/env bash

set -e
set -x

ruff check app tests
ruff format app tests --check
