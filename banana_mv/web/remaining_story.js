// RTX 5070 remaining story editor. Only shown after acknowledged stop.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const openButton = $('remaining-story-open');
  const dialog = $('remaining-story-dialog');
  const textarea = $('remaining-story-text');
  const summary = $('remaining-story-summary');
  const feedback = $('remaining-story-feedback');
  const previewButton = $('remaining-story-preview');
  const updateButton = $('remaining-story-update');
  const closeButton = $('remaining-story-close');
  let opened = null;
  let pending = false;
  let previewedText = null;

  async function jsonApi(url, data) {
    const res = await fetch(url, data ? {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    } : {cache:'no-store'});
    const parsed = await res.json().catch(() => ({}));
    if (!res.ok) throw Error(parsed.error || '服務回應錯誤：' + res.status);
    return parsed;
  }
  function busy(value) {
    pending = value;
    previewButton.disabled = value;
    updateButton.disabled = value || !previewedText || previewedText !== textarea.value;
    openButton.disabled = value;
    textarea.disabled = value;
  }
  function info(message, error = false) {
    feedback.textContent = message;
    feedback.style.color = error ? '#ffb2a7' : '';
  }
  window.renderRemainingStoryButton = function(job) {
    const segs = job?.segments || [];
    const first = segs.findIndex(s => s.status !== 'done');
    const editable = job?.request?.director_schema === 6 &&
      ['cancelled','interrupted','error'].includes(job.status) &&
      first >= 0 && segs.slice(first).every(s => s.status !== 'done');
    openButton.hidden = !editable;
    if (editable) openButton.textContent = '修改剩餘劇情（第 ' + (first + 1) + ' 段起）';
  };
  openButton.onclick = async () => {
    if (pending) return;
    openButton.disabled = true;
    try {
      const jobId = typeof active === 'string' ? active : '';
      if (!jobId) throw Error('請先選取要修改的專案。');
      const data = await jsonApi('/api/mv/remaining-story?id=' + encodeURIComponent(jobId));
      opened = data;
      previewedText = null;
      textarea.value = data.text;
      summary.textContent = '前 ' + data.locked_clips + ' 段保留；從第 ' +
        data.from_clip + ' 段修改，共 ' + data.remaining +
        ' 段。段號與時間標頭請保留，只改下面事件文字。';
      info('修改後先「檢查變更」，再「採用新劇情」。採用不會自動啟動 H3。');
      busy(false);
      dialog.showModal();
      textarea.focus();
    } catch (e) {
      alert(e.message);
    } finally { openButton.disabled = false; }
  };
  closeButton.onclick = () => {
    if (!pending) dialog.close();
  };
  dialog.addEventListener('cancel', event => { if (pending) event.preventDefault(); });
  textarea.addEventListener('input', () => {
    previewedText = null;
    updateButton.disabled = true;
    info('草稿已修改；請重新按「檢查變更」。');
  });
  previewButton.onclick = async () => {
    if (!opened || pending) return;
    busy(true);
    try {
      const result = await jsonApi('/api/mv/remaining-story/preview', {
        id: opened.id, revision: opened.revision, text: textarea.value
      });
      previewedText = result.changed_clips.length ? textarea.value : null;
      info(result.changed_clips.length
        ? '檢查完成：只更動第 ' + result.changed_clips.join('、') +
          ' 段事件。前 ' + (result.from_clip - 1) +
          ' 段不動；續跑會從第 ' + result.from_clip + ' 段開始。'
        : '沒有修改內容；不需要採用。');
    } catch (e) { previewedText = null; info(e.message, true); }
    finally { busy(false); }
  };
  updateButton.onclick = async () => {
    if (!opened || pending || previewedText !== textarea.value) return;
    if (!confirm('採用新的剩餘通告單？已完成影片不動。更新後請使用原本的「續跑未完成段落」。')) return;
    busy(true);
    try {
      const result = await jsonApi('/api/mv/remaining-story/update', {
        id: opened.id, revision: opened.revision, text: textarea.value
      });
      info(result.message);
      opened = null;
      dialog.close();
      if (typeof poll === 'function') void poll();
      alert(result.message);
    } catch (e) { info(e.message, true); }
    finally { busy(false); }
  };
})();
