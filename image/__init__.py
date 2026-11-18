"""Image/GIF studio: campaign generation (campaign_generator), image compositing and local image
models (visual_engine), template layout analysis (layout_analyzer), copy and campaign packaging
(agency_suite). These were top-level modules of the same names.

Kept free of imports: scripts/render_local_image.py imports visual_engine inside the separate
.venv-image environment, so importing this package must not pull in the server stack.
"""
