# Define targets
.PHONY: install start

# Target to install package
install:
	uv sync --frozen

# Target to start the Stremio Addon server
start:
	uv run python -m server.main
