#!/bin/bash

sudo pip install uv --break-system-packages
echo 'eval "$(uv generate-shell-completion bash)"' >> ~/.bashrc
echo 'eval "$(uvx --generate-shell-completion bash)"' >> ~/.bashrc
. ~/.bashrc
