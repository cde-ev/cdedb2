#!/bin/bash

cd "$(dirname "$0")/.." && PATTERNS="${@:1}" make single-check
