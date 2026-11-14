"""
Patch JS in index.html to add live bidirectional prompt synchronization,
clear stale names on upload, and update sample presets.
"""
from pathlib import Path
import re

INDEX_PATH = Path(r"c:\Users\mohamed redha\Desktop\marketing-agency\index.html")

def patch_js():
    code = INDEX_PATH.read_text(encoding="utf-8")

    # 1. Add updateWelcomePromptWithLiveFields definition before syncCurrentFields
    helper_code = '''
    // Dynamically updates promptInput with live-typed team member details
    function updateWelcomePromptWithLiveFields(name, role, dept) {
      if (!promptInput || currentPostType !== 'team_welcome') return;
      const bName = resolveActiveBrandName() || 'our company';
      const pName = (name && name.trim()) || 'our new team member';
      const pRole = (role && role.trim()) || 'Leadership Team';
      const pDept = (dept && dept.trim()) ? ` in the ${dept.trim()}` : '';

      const cur = promptInput.value || '';
      if (!cur.trim() || /welcoming\s+(?:new\s+)?team\s+member/i.test(cur) || /A high-end commercial campaign portrait/i.test(cur) || /Template swap:/i.test(cur)) {
        promptInput.value = `A high-end commercial campaign portrait for ${bName} welcoming new team member ${pName}, ${pRole}${pDept}, to the team. Shot on an 85mm lens with softbox studio lighting, clean background, and generous negative space for brand typography.`;
        if (charCount) charCount.textContent = promptInput.value.length;
      }
    }
'''

    # Insert before "function renderPostTypeFields"
    target = "function renderPostTypeFields(typeId) {"
    assert target in code, "renderPostTypeFields not found"
    code = code.replace(target, helper_code + "\n    " + target, 1)

    # 2. Update syncCurrentFields in renderPostTypeFields
    old_sync = '''      function syncCurrentFields() {
        const values = {};
        container.querySelectorAll('.pt-guided-input').forEach(inp => {
          values[inp.id] = inp.value.trim();
        });
        if (typeId === 'team_welcome') {
          currentPersonName = values['pt-member-name'] || (personNameInput && personNameInput.value.trim()) || '';
          currentPersonTitle = values['pt-member-role'] || (personTitleInput && personTitleInput.value.trim()) || '';
          if (personNameInput && values['pt-member-name'] !== undefined) personNameInput.value = values['pt-member-name'];
          if (personTitleInput && values['pt-member-role'] !== undefined) personTitleInput.value = values['pt-member-role'];
          const pStrip = document.getElementById('personalization-strip');
          if (pStrip) pStrip.classList.remove('hidden');
        } else {
          const pStrip = document.getElementById('personalization-strip');
          if (pStrip) pStrip.classList.add('hidden');
        }
        if (typeId === 'team_welcome') {
          if (personNameInput && currentPersonName) personNameInput.value = currentPersonName;
          if (personTitleInput && currentPersonTitle) personTitleInput.value = currentPersonTitle;
        }
      }'''

    new_sync = '''      function syncCurrentFields() {
        const values = {};
        container.querySelectorAll('.pt-guided-input').forEach(inp => {
          values[inp.id] = inp.value.trim();
        });
        if (typeId === 'team_welcome') {
          currentPersonName = values['pt-member-name'] || '';
          currentPersonTitle = values['pt-member-role'] || '';
          if (personNameInput) personNameInput.value = currentPersonName;
          if (personTitleInput) personTitleInput.value = currentPersonTitle;
          updateWelcomePromptWithLiveFields(currentPersonName, currentPersonTitle, values['pt-member-dept']);
        }
      }'''

    assert old_sync in code, "old_sync not found"
    code = code.replace(old_sync, new_sync, 1)

    # 3. Update uploadVisualAssetFile for slot === 'subject'
    old_upload_subject = '''        if (slot === 'subject') {
          activeSubjectAsset = assetObj;
          currentUploadedImageUrl = data.file_url;
          
          // Auto-extract candidate person name from uploaded photo filename if meaningful
          const originalName = (file && file.name) || data.filename || '';
          const candidateName = extractPersonNameFromFilename(originalName);
          if (candidateName) {
            if (personNameInput) personNameInput.value = candidateName;
            const ptName = document.getElementById('pt-member-name');
            if (ptName) ptName.value = candidateName;
            currentPersonName = candidateName;
          } else {
            sanitizePersonNameFields();
          }
          
          const knownName = (personNameInput && personNameInput.value.trim()) || currentPersonName || '';
          showToast(knownName
            ? `Subject photo loaded for ${knownName} (${data.width}×${data.height})`
            : `Subject photo loaded (${data.width}×${data.height}). You can type the member name in the personalization field.`, true);'''

    new_upload_subject = '''        if (slot === 'subject') {
          activeSubjectAsset = assetObj;
          currentUploadedImageUrl = data.file_url;
          
          // Auto-extract candidate person name from uploaded photo filename if meaningful
          const originalName = (file && file.name) || data.filename || '';
          const candidateName = extractPersonNameFromFilename(originalName);
          if (candidateName) {
            currentPersonName = candidateName;
            if (personNameInput) personNameInput.value = candidateName;
            const ptName = document.getElementById('pt-member-name');
            if (ptName) ptName.value = candidateName;
            updateWelcomePromptWithLiveFields(candidateName, currentPersonTitle || 'Leadership Team', '');
            showToast(`Subject photo loaded for ${candidateName} (${data.width}×${data.height})`, true);
          } else {
            // New upload without recognizable person name:
            // Explicitly clear old person name so it NEVER inherits an old or hardcoded name from previous uploads!
            currentPersonName = '';
            currentPersonTitle = '';
            if (personNameInput) personNameInput.value = '';
            const ptName = document.getElementById('pt-member-name');
            if (ptName) {
              ptName.value = '';
              ptName.focus();
            }
            if (personTitleInput) personTitleInput.value = '';
            const ptRole = document.getElementById('pt-member-role');
            if (ptRole) ptRole.value = '';
            
            // Clean prompt
            if (promptInput && currentPostType === 'team_welcome') {
              updateWelcomePromptWithLiveFields('', '', '');
            }
            showToast(`Subject photo loaded (${data.width}×${data.height}). Please enter the member's name in Stage 2.`, true);
          }'''

    assert old_upload_subject in code, "old_upload_subject not found"
    code = code.replace(old_upload_subject, new_upload_subject, 1)

    # 4. Update btnSamplePortrait and btnSamplePopout
    old_sample_popout = '''        if (promptInput && (!promptInput.value.trim() || promptInput.value.includes('Tesla'))) {
          promptInput.value = 'Template swap: Replace original subject with new subject in monochrome B&W with 2.5D head pop-out over WELCOME typography';
          if (charCount) charCount.textContent = promptInput.value.length;
        }
        showToast('Loaded Sekawan 2.5D Pop-Out Benchmark (Template + Subject Portrait)!', true);'''

    new_sample_popout = '''        const ptName = document.getElementById('pt-member-name');
        const ptRole = document.getElementById('pt-member-role');
        const sampleName = 'Sara Al-Khalifa';
        const sampleRole = 'Senior AI Research Engineer';
        if (ptName) ptName.value = sampleName;
        if (ptRole) ptRole.value = sampleRole;
        if (personNameInput) personNameInput.value = sampleName;
        if (personTitleInput) personTitleInput.value = sampleRole;
        currentPersonName = sampleName;
        currentPersonTitle = sampleRole;
        if (currentPostType === 'team_welcome') {
          updateWelcomePromptWithLiveFields(sampleName, sampleRole, '');
        }
        showToast('Loaded Sekawan 2.5D Pop-Out Benchmark (Sara Al-Khalifa)!', true);'''

    assert old_sample_popout in code, "old_sample_popout not found"
    code = code.replace(old_sample_popout, new_sample_popout, 1)

    old_sample_portrait = '''        activeSubjectAsset = {
          url: '/test_assets/raw_subject.jpg',
          path: 'test_assets/raw_subject.jpg',
          filename: 'raw_subject.jpg',
          width: 1024,
          height: 682,
          thumb: '/test_assets/raw_subject.jpg'
        };
        activeTemplateAsset = null;
        currentUploadedImageUrl = '/test_assets/raw_subject.jpg';
        updateVisualStageUI();
        showToast('Loaded Studio Portrait (Woman in Abaya) as Subject to Use!', true);'''

    new_sample_portrait = '''        activeSubjectAsset = {
          url: '/test_assets/raw_subject.jpg',
          path: 'test_assets/raw_subject.jpg',
          filename: 'raw_subject.jpg',
          width: 1024,
          height: 682,
          thumb: '/test_assets/raw_subject.jpg'
        };
        activeTemplateAsset = null;
        currentUploadedImageUrl = '/test_assets/raw_subject.jpg';
        updateVisualStageUI();

        const ptName = document.getElementById('pt-member-name');
        const ptRole = document.getElementById('pt-member-role');
        const sampleName = 'Sara Al-Khalifa';
        const sampleRole = 'Senior AI Research Engineer';
        if (ptName) ptName.value = sampleName;
        if (ptRole) ptRole.value = sampleRole;
        if (personNameInput) personNameInput.value = sampleName;
        if (personTitleInput) personTitleInput.value = sampleRole;
        currentPersonName = sampleName;
        currentPersonTitle = sampleRole;
        if (currentPostType === 'team_welcome') {
          updateWelcomePromptWithLiveFields(sampleName, sampleRole, '');
        }
        showToast('Loaded Studio Portrait: Sara Al-Khalifa (Senior AI Research Engineer)!', true);'''

    assert old_sample_portrait in code, "old_sample_portrait not found"
    code = code.replace(old_sample_portrait, new_sample_portrait, 1)

    INDEX_PATH.write_text(code, encoding="utf-8")
    print("JS patch applied successfully!")

if __name__ == "__main__":
    patch_js()

