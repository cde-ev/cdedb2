#!/bin/bash

sudo pip install uv --break-system-packages
# shellcheck disable=SC2016
echo 'eval "$(uv generate-shell-completion bash)"' >> ~/.bashrc
# shellcheck disable=SC2016
echo 'eval "$(uvx --generate-shell-completion bash)"' >> ~/.bashrc
# shellcheck disable=SC1090
. ~/.bashrc
