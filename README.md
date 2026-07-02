# Stremio MovieBox Addon

Watch the massive MovieBox catalog directly from Stremio! This addon bridges MovieBox's internal APIs (Legacy, Web, and Mobile) straight into your Stremio experience, serving up high-quality streams with full audio dub and subtitle support.

## Features

- **Blazing Fast Searches:** Concurrently scrapes multiple MovieBox APIs so you never miss a stream.
- **Smart Grouping:** Intelligently merges identical streams and organizes them beautifully by resolution and language.
- **Web UI Dashboard:** Customize exactly what you want to see—set minimum resolutions, prioritize your native language, and tweak layout styles through a sleek configuration page.
- **Stremio Native:** Fully integrates with Stremio's Cinemeta system for perfect metadata matching.

---

## Getting Started (Recommended)

The absolute easiest way to run the addon is using Docker. You don't need to download the source code at all.

### Option A: Docker Run (Quickest)

Just run this single command in your terminal:

```bash
docker run -d --name stremio-moviebox -p 8000:8000 --restart unless-stopped mesamirh/stremio-moviebox:latest
```

### Option B: Docker Compose

If you prefer `docker-compose`, create a `docker-compose.yml` file anywhere on your computer with the following content:

```yaml
version: "3.8"
services:
  stremio-moviebox:
    image: mesamirh/stremio-moviebox:latest
    container_name: stremio-moviebox
    restart: unless-stopped
    ports:
      - "8000:8000"
```

Then start it up with:

```bash
docker-compose up -d
```

### Option C: Build the Docker Image Locally

If you want to build the absolute latest version of the image from the source code, run the following commands:

```bash
git clone https://github.com/mesamirh/stremio-moviebox.git
cd stremio-moviebox
docker build -t mesamirh/stremio-moviebox:latest .
docker run -d --name stremio-moviebox -p 8000:8000 --restart unless-stopped mesamirh/stremio-moviebox:latest
```

---

## How to Install in Stremio

Once the Docker container is running, you need to add it to Stremio:

1. Open your browser and go to: `http://127.0.0.1:8000/configure/` (or replace `127.0.0.1` with the IP address of your server).
2. Tweak the settings to your liking (choose your preferred language, resolution limits, etc.).
3. Click the **"Install Addon"** button at the bottom of the page to automatically link it to your Stremio app.

---

## For Developers (Manual Setup)

If you want to modify the code or run it natively without Docker, you will need Python 3.11+.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mesamirh/stremio-moviebox.git
   cd stremio-moviebox
   ```
2. **Install dependencies** (we recommend `uv` for speed, but `pip` works too!):
   ```bash
   uv sync
   # OR: pip install -r requirements.txt
   ```
3. **Start the local server:**
   ```bash
   make start
   ```
   The Uvicorn server will boot up on `http://127.0.0.1:8000`.

---

## Project Structure

- **`server/`**: The FastAPI core. Manages routing, Stremio addon manifest generation, and serves the configuration Web UI.
- **`streaming/`**: The processing engine. It translates Stremio's Cinemeta ID requests into MovieBox queries, parses the multi-API responses, filters out duplicates, and intelligently ranks streams based on user configuration.
- **`moviebox/`**: The scraper clients. Contains the reverse-engineered API clients that securely authenticate and extract high-speed streaming links from MovieBox's v1 (Legacy), v2 (Web), and v3 (Mobile) endpoints concurrently.
- **`web/`**: The frontend assets. Contains the HTML, CSS, and vanilla JavaScript that power the beautiful configuration dashboard.

---

## Disclaimer

This addon is built purely for educational purposes. It scrapes publicly available content from third-party APIs. The developers of this repository are not affiliated with MovieBox or Stremio in any capacity.
