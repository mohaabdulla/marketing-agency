"""Video Studio: storyboard videos, AI narration, editing, rendering and delivery checks.

api.py           the /api/video router; route groups live in routes/
sequence.py      storyboard sequence render and client kit;  director.py  storyboard planning
voice.py         offline narration;  company_intro.py  research-driven company videos
stock.py         licensed stock footage search (Pexels, Pixabay) with credits
engine.py        AI model video generation and image animation;  editor.py  FFmpeg timeline renderer
projects.py, revisions.py, storage.py, assets.py, jobs.py   persistence and background jobs
Modules that existed before the move were top-level video_<name>.py files.
"""
