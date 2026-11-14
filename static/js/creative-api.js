/**
 * Creative Studio Client API
 * Connects the frontend to the layered Creative Engine (Still, Motion/GIF, Direct MP4).
 */
(function(window) {
    'use strict';

    const CreativeAPI = {
        async getPresets() {
            const res = await fetch('/api/creative/presets');
            if (!res.ok) throw new Error('Failed to load creative presets');
            return await res.json();
        },

        async listProjects() {
            const res = await fetch('/api/creative/projects');
            if (!res.ok) throw new Error('Failed to list creative projects');
            return await res.json();
        },

        async loadProject(projectId) {
            const res = await fetch(`/api/creative/projects/${encodeURIComponent(projectId)}`);
            if (!res.ok) throw new Error(`Project ${projectId} not found`);
            return await res.json();
        },

        async saveProject(project) {
            const res = await fetch('/api/creative/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to save creative project');
            }
            return await res.json();
        },

        async auditProject(projectOrId) {
            const body = typeof projectOrId === 'string'
                ? { project_id: projectOrId }
                : { project: projectOrId };
            const res = await fetch('/api/creative/qa/audit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'QA audit failed');
            }
            return await res.json();
        },

        async renderStill(params) {
            const res = await fetch('/api/creative/render/still', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Still render failed');
            }
            return await res.json();
        },

        async renderGif(params) {
            const res = await fetch('/api/creative/render/gif', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'GIF render failed');
            }
            return await res.json();
        },

        async renderMp4(params) {
            const res = await fetch('/api/creative/render/mp4', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Direct MP4 render failed');
            }
            return await res.json();
        },

        async bridgeToVideo(outputPath, name) {
            const res = await fetch('/api/creative/bridge-to-video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ output_path: outputPath, name })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Bridge to Video Studio failed');
            }
            return await res.json();
        }
    };

    window.CreativeAPI = CreativeAPI;
})(window);

