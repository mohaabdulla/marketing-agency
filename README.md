# Lexnis Campaign Studio

> **Industrial AI & Automation B2B Marketing Engine**  
> Complete system powered by **Free OpenAI Models** for technical copywriting, **Free Google Search** for real-time market/technical intelligence, and **FLUX Realism AI** for cinematic visual asset synthesis. **Zero API keys required.**

---

## 🧠 How the agency pipeline works (v2)

1. **Research**: scrapes any product URL you paste in the prompt, then researches the product with Gemini + Google Search grounding (if `GEMINI_API_KEY` is set) or keyless search scraping as a fallback.
2. **Strategist**: turns the research into a creative brief (audience, pain points, benefits, verified proof points, angle).
3. **Copywriter**: writes the post as strict JSON: hook, caption, 3 benefits, CTA, 10-14 hashtags, on-image headline, alt text and an art-directed image prompt. Output is cleaned for Instagram (no `**markdown**`) and kept under 2,200 chars.
4. **Art director**: renders the image on the Pollinations gen API, crops it to exactly 1080×1350, sharpens it and adds a headline + brand tag overlay. Both the post and the clean image are saved.

### 🔑 Watermark-free images

Without a key, Pollinations serves its anonymous tier: a low-res image (686×858) from a weak model, with the Pollinations logo added. To fix that:

1. Create a free account at **https://enter.pollinations.ai/keys** and copy the **secret key (`sk_...`)**.
2. Put it in `.env`: `POLLINATIONS_API_KEY=sk_...` (see `.env.example`).
3. Restart `python server.py`. The amber warning in the dashboard disappears when the key is active.

> 💡 **Tip:** to get the most accurate copy, paste the product page URL in the prompt, e.g. `Launch post for our new serum https://yourshop.com/products/serum`.

---

## ⚡ Key Highlights

- **100% Free — No API Key Required**: Powered by the official `openai` Python library connected to free OpenAI-compatible inference endpoints.
- **Superior AI Image Generation (FLUX Realism)**:
  - Upgraded to **`flux-realism`** (Black Forest Labs fine-tuned photorealism model), far superior to standard diffusion for industrial machinery, hardware, and physical materials.
  - Automatic **`enhance=true`** neural prompt optimization.
  - Camera-lens cinematography injection (e.g., *Hasselblad H6D-100c 85mm f/1.4, volumetric specular lighting, 8k UHD*).
  - Model Switcher in the dashboard: choose between **🌟 FLUX Realism** (Photorealistic), **⚡ FLUX.1 Flagship**, and **🚀 SDXL Turbo**.
- **Free Unlimited Google Search Research**:
  - Automatically queries Google for your prompt/concept using native scraping and `googlesearch-python`.
  - Injects real-time search intelligence into the copywriter AI so B2B copy is grounded in real specs, competitor data, and live industry benchmarks.
  - No Google API key, no custom search engine ID, and zero linter warnings.
- **Dual-Mode Engine**: Run via standalone browser client ([`index.html`](file:///c:/Users/mohamed%20redha/Desktop/marketing-agency/index.html)) or high-performance Python FastAPI backend ([`server.py`](file:///c:/Users/mohamed%20redha/Desktop/marketing-agency/server.py)).
- **High-Tech Obsidian Dark UI**: Tailored specifically for an industrial AI firm with obsidian black background (`#07090e`), electric cyan (`#00f0ff`) and ultraviolet (`#8b5cf6`) accents, micro-glow badges, and telemetry indicators.
- **Python CLI Tool ([`campaign_generator.py`](file:///c:/Users/mohamed%20redha/Desktop/marketing-agency/campaign_generator.py))**:
  - Rich terminal CLI interface with panels, tables, and progress spinners.
  - Automatic visual download and package export (`.jpg`, `.json`, `.md`).
- **FastAPI Web Server ([`server.py`](file:///c:/Users/mohamed%20redha/Desktop/marketing-agency/server.py))**:
  - Serves dashboard with disk export endpoint (`/api/export`) and Google search endpoint (`/api/search`).
- **Instagram-Ready Visual Asset Format**:
  - 4:5 vertical aspect ratio (`1080×1350`).
  - Dynamic image synthesis with Lexnis typography overlay burn-in (`text=LEXNIS%20TECHNOLOGIES%0AINDUSTRIAL%20AI`).
- **Marketing Copy & Caption Studio**:
  - Structured output: Campaign Hook, Engaging B2B Caption Body, Technical Highlights/ROI Metrics, Curated Hashtags, and Google Research Sources.
  - One-click copy with clipboard toast notifications.
  - Character counter with Instagram 2,200 character limit indicator.

---

## 🚀 How to Run

### Option 1: Start the Python FastAPI Server & Open Web UI
```bash
python server.py
```
1. Open **`http://localhost:8000`** in your browser.
2. The UI will show `ENGINE: OPENAI PYTHON ENGINE (ONLINE)`.
3. Type any campaign idea (e.g. *"Autonomous cobot assembly line optimization for Lexnis"*) and click **Generate Campaign**.
4. The system automatically searches Google in real time, generates grounded copy, renders the photorealistic Flux Realism visual asset, and displays the Google sources.
5. You can switch models between **FLUX Realism**, **FLUX.1**, and **Turbo** right on the dashboard.
6. Click **"Export Package to Disk"** to save everything to the `output/` folder.

---

### Option 2: Run directly from the Terminal (CLI)
```bash
# Basic run with prompt argument (uses FLUX Realism by default):
python campaign_generator.py "Predictive maintenance IoT platform launch for Lexnis"

# Choose a specific image model and download asset to output/ folder:
python campaign_generator.py "Autonomous robotics fleet orchestration" --brand "Lexnis Technologies" --image-model black-forest-labs/flux.1.1-pro --download

# Interactive prompt (will ask for concept if omitted):
python campaign_generator.py
```

---

### Option 3: Double-Click `index.html` (Standalone Client)
You can open [`index.html`](file:///c:/Users/mohamed%20redha/Desktop/marketing-agency/index.html) directly in any browser without starting Python. It directly connects to the free OpenAI text engine and the photorealistic Flux visual generator with zero configuration.

---

## 🐍 Use as a Python Library in Your Code

```python
from campaign_generator import LexnisCampaignStudio

# Initialize free engine (no key required)
studio = LexnisCampaignStudio()

# 1. Search Google freely with no limits
search_results = studio.search_google("industrial IoT predictive maintenance", max_results=5)
for item in search_results:
    print(r"•", item["title"], item["url"])

# 2. Generate campaign grounded with Google search & photorealistic image
campaign = studio.generate_campaign(
    prompt="Digital twin platform for green gigafactories",
    tone="authoritative B2B enterprise",
    theme="dark cyber-physical smart factory with cyan telemetry",
    use_search=True,
    image_model="black-forest-labs/flux.1.1-pro",
    enhance_image=True,          # headline + brand overlay on the image
    brand="Lexnis Technologies"
)

# Access structured data
print("Hook:", campaign.hook)
print("Caption:", campaign.caption)
print("Highlights:", campaign.highlights)
print("Google Sources:", [r["title"] for r in campaign.search_results])
print("Visual Asset URL:", campaign.image_url)

# Save image and export full package to disk
saved_files = studio.export_campaign(campaign, output_dir="output")
print("Saved files:", saved_files)
```
